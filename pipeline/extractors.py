"""Niveau 3 - Extraction de transactions depuis plusieurs formats de fichiers.

Chaque format est converti en "lignes" au format CSV (dict colonne -> valeur),
puis passe par le MÊME traitement pur (processing.process) que les CSV.

  .csv               -> lecture directe
  .png / .jpg        -> OCR (Tesseract) puis parsing du texte reconnu
  .txt               -> petit modèle de langage (Ollama) qui renvoie du JSON

Les fonctions parse_* sont pures (testables sans Tesseract ni Ollama) ;
run_ocr / ask_slm font les appels externes.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import PurePosixPath
from typing import Dict, List

from . import config
from .generate import COLUMNS
from .processing import InvalidTransaction
from .retry import retry

log = logging.getLogger(__name__)

Row = Dict[str, str]

CSV_EXT = {".csv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg"}
TEXT_EXT = {".txt"}
SUPPORTED_EXT = CSV_EXT | IMAGE_EXT | TEXT_EXT

IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def extension(key: str) -> str:
    return PurePosixPath(key).suffix.lower()


def is_supported(key: str) -> bool:
    return extension(key) in SUPPORTED_EXT


def extract_rows(key: str, content: bytes) -> List[Row]:
    ext = extension(key)
    if ext in CSV_EXT:
        return list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    if ext in IMAGE_EXT:
        text = run_ocr(content)
        log.info("%s : OCR -> %d caractères reconnus", key, len(text))
        return parse_ocr_text(text)
    if ext in TEXT_EXT:
        source = content.decode("utf-8")
        answer = ask_slm(source)
        log.info("%s : réponse du modèle %s", key, answer)
        return parse_slm_answer(answer, source)
    raise InvalidTransaction(f"format non supporté : {key}")


# --------------------------------------------------------------------------- OCR
def run_ocr(image_bytes: bytes) -> str:
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes))
    # psm 6 = "un bloc de texte uniforme" : adapté à un tableau ligne par ligne
    return pytesseract.image_to_string(image, config="--psm 6")


_OCR_LINE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})[ T]+(\d{2}:\d{2}:\d{2})\s*;(.*)$")


def _clean_iban(value: str) -> str:
    # l'OCR insère parfois des espaces au milieu d'un IBAN
    return re.sub(r"\s+", "", value).upper()


def parse_ocr_text(text: str) -> List[Row]:
    """Texte OCR -> lignes. Les lignes qui ne ressemblent pas à une transaction
    (titre, lignes vides) sont ignorées ; une transaction mal lue lève une erreur."""
    rows = []
    for raw in text.splitlines():
        m = _OCR_LINE_RE.match(raw)
        if not m:
            continue
        date, time, rest = m.groups()
        parts = [p.strip() for p in rest.split(";")]
        if len(parts) != 6:
            raise InvalidTransaction(f"OCR : ligne illisible {raw!r}")
        src, pays_src, banque, dst, pays_dst, montant = parts
        row = {
            "datetime_transaction": f"{date}T{time}",
            "iban_origine": _clean_iban(src),
            "pays_source": pays_src.upper(),
            "banque_source": " ".join(banque.split()),
            "iban_destinataire": _clean_iban(dst),
            "pays_destinataire": pays_dst.upper(),
            "montant": montant.replace(",", ".").replace(" ", ""),
        }
        _check_fields(row, origin="OCR")
        rows.append(row)
    if not rows:
        raise InvalidTransaction("OCR : aucune transaction reconnue")
    return rows


def _check_fields(row: Row, origin: str) -> None:
    for col in ("iban_origine", "iban_destinataire"):
        if not IBAN_RE.match(row[col]):
            raise InvalidTransaction(f"{origin} : IBAN invalide {row[col]!r}")
    for col in ("pays_source", "pays_destinataire"):
        if not COUNTRY_RE.match(row[col]):
            raise InvalidTransaction(f"{origin} : code pays invalide {row[col]!r}")


# ------------------------------------------------------------ Small Language Model
SLM_SCHEMA = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {c: {"type": "string"} for c in COLUMNS},
                "required": COLUMNS,
            },
        }
    },
    "required": ["transactions"],
}

SLM_PROMPT = """Tu es un extracteur de données bancaires. Extrais TOUS les virements du texte.
Pour chaque virement, renvoie :
- datetime_transaction : format AAAA-MM-JJTHH:MM:SS (ex : 08h30 -> 08:30:00)
- iban_origine : l'IBAN du compte qui envoie, recopié EXACTEMENT
- pays_source : code pays ISO à 2 lettres de la banque qui envoie (FR, DE, ES, IT...)
- banque_source : nom de la banque qui envoie
- iban_destinataire : l'IBAN du compte qui reçoit, recopié EXACTEMENT
- pays_destinataire : code ISO à 2 lettres du pays du destinataire (France=FR, Allemagne=DE, Espagne=ES, Italie=IT)
- montant : nombre avec un point décimal, sans devise (ex : 2750.00)

Texte :
\"\"\"
{text}
\"\"\""""


@retry(exceptions=(urllib.error.URLError, ConnectionError, TimeoutError),
       attempts=config.RETRY_ATTEMPTS, base_delay=config.RETRY_BASE_DELAY)
def ask_slm(text: str) -> str:
    payload = {
        "model": config.SLM_MODEL,
        "prompt": SLM_PROMPT.format(text=text),
        "format": SLM_SCHEMA,          # sortie structurée : JSON conforme au schéma
        "stream": False,
        "options": {"temperature": 0, "seed": 42},   # le plus déterministe possible
    }
    req = urllib.request.Request(
        f"{config.OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=config.SLM_TIMEOUT) as resp:
        return json.loads(resp.read())["response"]


def parse_slm_answer(answer: str, source_text: str) -> List[Row]:
    """Valide la réponse du modèle. Garde-fou anti-hallucination : chaque IBAN
    et chaque montant doit apparaître littéralement dans le texte source."""
    try:
        items = json.loads(answer)["transactions"]
    except (ValueError, KeyError, TypeError):
        raise InvalidTransaction(f"SLM : réponse non exploitable {answer[:200]!r}")
    if not items:
        raise InvalidTransaction("SLM : aucune transaction extraite")
    compact_source = re.sub(r"\s+", "", source_text).upper()
    rows = []
    for item in items:
        row = {c: str(item.get(c, "")).strip() for c in COLUMNS}
        for col in ("iban_origine", "iban_destinataire"):
            row[col] = _clean_iban(row[col])
        for col in ("pays_source", "pays_destinataire"):
            row[col] = row[col].upper()
        row["montant"] = row["montant"].replace(",", ".").replace(" ", "")
        _check_fields(row, origin="SLM")
        for col in ("iban_origine", "iban_destinataire", "montant"):
            if row[col].upper() not in compact_source:
                raise InvalidTransaction(
                    f"SLM : {col}={row[col]!r} absent du texte source (hallucination ?)")
        rows.append(row)
    return rows
