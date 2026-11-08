"""Niveau 1.1 - Génération de fichiers CSV de transactions financières.

Les données sont volontairement NON aléatoires : chaque exécution produit
exactement les mêmes fichiers, ce qui permet de connaître à l'avance les
résultats attendus (cf. tests/expected.py) et donc de tester la pipeline.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Dict, List, Tuple

COLUMNS = [
    "datetime_transaction",
    "iban_origine",
    "pays_source",
    "banque_source",
    "iban_destinataire",
    "pays_destinataire",
    "montant",
]

# Comptes fictifs : iban -> (pays, banque)
ACCOUNTS: Dict[str, Tuple[str, str]] = {
    "FR7610001000010000000000001": ("FR", "Banque Alpha"),
    "FR7610001000010000000000003": ("FR", "Banque Alpha"),
    "FR7610002000020000000000002": ("FR", "Banque Beta"),
    "DE89370400440532013000": ("DE", "Banque Gamma"),
    "ES9121000418450200051332": ("ES", "Banque Delta"),
    "IT60X0542811101000000123456": ("IT", "Banque Epsilon"),
}

FR1 = "FR7610001000010000000000001"
FR3 = "FR7610001000010000000000003"
FR2 = "FR7610002000020000000000002"
DE1 = "DE89370400440532013000"
ES1 = "ES9121000418450200051332"
IT1 = "IT60X0542811101000000123456"

# (datetime, iban origine, iban destinataire, montant)
DATASET: Dict[str, List[Tuple[str, str, str, str]]] = {
    "transactions_2026-01-01.csv": [
        ("2026-01-01T09:00:00", FR1, DE1, "1200.00"),
        ("2026-01-01T10:30:00", FR2, ES1, "5000.00"),  # pile 5000 -> NON flaggé
        ("2026-01-01T11:15:00", DE1, FR1, "7500.50"),  # flag
        ("2026-01-01T14:00:00", FR1, IT1, "300.00"),
        ("2026-01-01T16:45:00", ES1, FR2, "5000.01"),  # flag
    ],
    "transactions_2026-01-02.csv": [
        ("2026-01-02T08:00:00", IT1, FR1, "250.00"),
        ("2026-01-02T09:20:00", FR1, ES1, "8000.00"),  # flag
        ("2026-01-02T10:00:00", FR2, DE1, "450.75"),
        ("2026-01-02T12:30:00", DE1, IT1, "1000.00"),
        ("2026-01-02T15:00:00", FR2, FR1, "6200.00"),  # flag
        ("2026-01-02T17:10:00", ES1, DE1, "99.99"),
    ],
    "transactions_2026-01-03.csv": [
        ("2026-01-03T07:45:00", FR1, FR2, "150.00"),
        ("2026-01-03T08:30:00", DE1, ES1, "12000.00"),  # flag
        ("2026-01-03T09:00:00", IT1, DE1, "4999.99"),
        ("2026-01-03T11:11:00", FR2, IT1, "700.00"),
        ("2026-01-03T13:00:00", ES1, FR1, "2500.00"),
        ("2026-01-03T15:30:00", FR1, DE1, "5500.00"),  # flag
        ("2026-01-03T18:00:00", FR3, ES1, "100.00"),
    ],
}


def build_rows(entries: List[Tuple[str, str, str, str]]) -> List[Dict[str, str]]:
    rows = []
    for dt, src, dst, amount in entries:
        pays_src, banque_src = ACCOUNTS[src]
        pays_dst, _ = ACCOUNTS[dst]
        rows.append(
            {
                "datetime_transaction": dt,
                "iban_origine": src,
                "pays_source": pays_src,
                "banque_source": banque_src,
                "iban_destinataire": dst,
                "pays_destinataire": pays_dst,
                "montant": amount,
            }
        )
    return rows


def generate(out_dir: str | Path) -> List[Path]:
    """Écrit les fichiers CSV dans out_dir et renvoie la liste des chemins."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, entries in DATASET.items():
        rows = build_rows(entries)
        # Point d'injection de bug pour le scénario d'échec (Niveau 1.6)
        if os.getenv("INJECT_BUG") == "generation":
            rows[0]["montant"] = "12O0.00"  # lettre O au lieu du chiffre 0
        path = out / filename
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written
