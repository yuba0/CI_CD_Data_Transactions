"""Niveau 3 - Sources non structurées, générées de façon déterministe :
- des IMAGES de relevés (lues par OCR)
- des TEXTES bruts rédigés en langage naturel (lus par un petit modèle de langage)
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from .generate import ACCOUNTS, DE1, ES1, FR1, FR2, FR3, IT1

# (datetime, iban origine, iban destinataire, montant)
IMAGE_DATASET: Dict[str, List[Tuple[str, str, str, str]]] = {
    "releve_2026-01-04.png": [
        ("2026-01-04T09:00:00", FR1, DE1, "1500.00"),
        ("2026-01-04T10:15:00", DE1, IT1, "9100.00"),   # flag
        ("2026-01-04T14:40:00", IT1, FR2, "320.50"),
        ("2026-01-04T17:05:00", ES1, FR3, "5001.00"),   # flag
    ],
}

TEXT_DATASET: Dict[str, List[Tuple[str, str, str, str]]] = {
    "message_2026-01-05.txt": [
        ("2026-01-05T08:30:00", FR2, ES1, "2750.00"),
        ("2026-01-05T16:20:00", IT1, DE1, "6400.00"),   # flag
    ],
}

TEXT_TEMPLATES = [
    "Bonjour, je vous confirme que le {date} à {heure}, la {banque} ({pays_src}) a "
    "exécuté un virement de {montant} euros depuis le compte {src} vers le compte "
    "{dst} situé en {pays_dst_nom}.",
    "Autre opération à signaler : le {date} vers {heure}, le client du compte {src} "
    "({banque}, {pays_src}) a envoyé {montant} EUR au bénéficiaire {dst} ({pays_dst_nom}).",
]

COUNTRY_NAMES = {"FR": "France", "DE": "Allemagne", "ES": "Espagne", "IT": "Italie"}


def _line(dt: str, src: str, dst: str, amount: str) -> str:
    pays_src, banque = ACCOUNTS[src]
    pays_dst, _ = ACCOUNTS[dst]
    return " ; ".join([dt.replace("T", " "), src, pays_src, banque, dst, pays_dst, amount])


def render_image(entries, path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=26)
    lines = ["RELEVE DE VIREMENTS", ""] + [_line(*e) for e in entries]
    img = Image.new("L", (1700, 90 + 50 * len(lines)), color=255)
    draw = ImageDraw.Draw(img)
    for i, text in enumerate(lines):
        draw.text((40, 40 + 50 * i), text, fill=0, font=font)
    img.save(path)


def render_text(entries) -> str:
    paragraphs = []
    for i, (dt, src, dst, amount) in enumerate(entries):
        pays_src, banque = ACCOUNTS[src]
        pays_dst, _ = ACCOUNTS[dst]
        date, heure = dt.split("T")
        paragraphs.append(TEXT_TEMPLATES[i % len(TEXT_TEMPLATES)].format(
            date=date, heure=heure[:5].replace(":", "h"), banque=banque, pays_src=pays_src,
            montant=amount, src=src, dst=dst, pays_dst_nom=COUNTRY_NAMES[pays_dst]))
    return "\n\n".join(paragraphs) + "\n"


def generate_images(out_dir) -> List[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, entries in IMAGE_DATASET.items():
        render_image(entries, out / name)
        paths.append(out / name)
    return paths


def generate_texts(out_dir) -> List[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, entries in TEXT_DATASET.items():
        (out / name).write_text(render_text(entries), encoding="utf-8")
        paths.append(out / name)
    return paths
