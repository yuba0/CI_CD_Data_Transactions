"""Niveau 1.2 - Fonctions de traitement PURES.

Aucune fonction ici ne lit de fichier, n'accède au réseau ou à la base :
elles prennent des données en entrée et renvoient de nouvelles données,
sans modifier leurs arguments. Elles sont donc testables unitairement.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Mapping

FLAG_THRESHOLD = Decimal("5000")

REQUIRED_COLUMNS = (
    "datetime_transaction",
    "iban_origine",
    "pays_source",
    "banque_source",
    "iban_destinataire",
    "pays_destinataire",
    "montant",
)


class InvalidTransaction(ValueError):
    """Ligne de CSV invalide (colonne manquante, montant illisible...)."""


@dataclass(frozen=True)
class Transaction:
    line_number: int
    datetime_transaction: datetime
    iban_origine: str
    pays_source: str
    banque_source: str
    iban_destinataire: str
    pays_destinataire: str
    montant: Decimal
    is_flagged: bool = False


@dataclass(frozen=True)
class ProcessingResult:
    transactions: List[Transaction]
    sent_by_iban: Dict[str, Decimal]
    sent_by_bank: Dict[str, Decimal]
    received_by_iban: Dict[str, Decimal]


def parse_row(row: Mapping[str, str], line_number: int) -> Transaction:
    missing = [c for c in REQUIRED_COLUMNS if not (row.get(c) or "").strip()]
    if missing:
        raise InvalidTransaction(f"ligne {line_number}: colonnes manquantes {missing}")
    try:
        montant = Decimal(row["montant"].strip())
    except InvalidOperation:
        raise InvalidTransaction(f"ligne {line_number}: montant invalide {row['montant']!r}")
    if montant <= 0:
        raise InvalidTransaction(f"ligne {line_number}: montant non positif {montant}")
    try:
        dt = datetime.fromisoformat(row["datetime_transaction"].strip())
    except ValueError:
        raise InvalidTransaction(
            f"ligne {line_number}: date invalide {row['datetime_transaction']!r}"
        )
    return Transaction(
        line_number=line_number,
        datetime_transaction=dt,
        iban_origine=row["iban_origine"].strip(),
        pays_source=row["pays_source"].strip(),
        banque_source=row["banque_source"].strip(),
        iban_destinataire=row["iban_destinataire"].strip(),
        pays_destinataire=row["pays_destinataire"].strip(),
        montant=montant,
    )


def parse_rows(rows: Iterable[Mapping[str, str]]) -> List[Transaction]:
    # line_number = numéro de ligne dans le fichier (1 = en-tête)
    return [parse_row(r, i) for i, r in enumerate(rows, start=2)]


def _sum_by(transactions: Iterable[Transaction], key) -> Dict[str, Decimal]:
    totals: Dict[str, Decimal] = {}
    for t in transactions:
        k = key(t)
        totals[k] = totals.get(k, Decimal("0")) + t.montant
    return totals


def sum_sent_by_iban(transactions: Iterable[Transaction]) -> Dict[str, Decimal]:
    return _sum_by(transactions, lambda t: t.iban_origine)


def sum_sent_by_bank(transactions: Iterable[Transaction]) -> Dict[str, Decimal]:
    return _sum_by(transactions, lambda t: t.banque_source)


def sum_received_by_iban(transactions: Iterable[Transaction]) -> Dict[str, Decimal]:
    return _sum_by(transactions, lambda t: t.iban_destinataire)


def is_suspicious(montant: Decimal, threshold: Decimal = FLAG_THRESHOLD) -> bool:
    """Flag si le montant est STRICTEMENT au-dessus du seuil."""
    return montant > threshold


def flag_transactions(
    transactions: Iterable[Transaction], threshold: Decimal = FLAG_THRESHOLD
) -> List[Transaction]:
    # replace() crée une nouvelle instance : l'entrée n'est pas modifiée
    return [replace(t, is_flagged=is_suspicious(t.montant, threshold)) for t in transactions]


def process(rows: Iterable[Mapping[str, str]]) -> ProcessingResult:
    """Point d'entrée : lignes brutes du CSV -> résultats du traitement."""
    transactions = flag_transactions(parse_rows(rows))
    return ProcessingResult(
        transactions=transactions,
        sent_by_iban=sum_sent_by_iban(transactions),
        sent_by_bank=sum_sent_by_bank(transactions),
        received_by_iban=sum_received_by_iban(transactions),
    )
