"""Tests unitaires des fonctions pures (aucune infra nécessaire)."""
from decimal import Decimal

import pytest

from pipeline import generate
from pipeline.processing import (
    InvalidTransaction,
    flag_transactions,
    is_suspicious,
    parse_rows,
    process,
    sum_received_by_iban,
    sum_sent_by_bank,
    sum_sent_by_iban,
)
from tests import expected


def all_rows():
    rows = []
    for entries in generate.DATASET.values():
        rows += generate.build_rows(entries)
    return rows


def row(montant="100.00", **kw):
    base = {
        "datetime_transaction": "2026-01-01T10:00:00",
        "iban_origine": "A", "pays_source": "FR", "banque_source": "B1",
        "iban_destinataire": "C", "pays_destinataire": "DE", "montant": montant,
    }
    base.update(kw)
    return base


@pytest.mark.parametrize("montant,flag", [
    ("4999.99", False), ("5000.00", False), ("5000.01", True), ("12000", True),
])
def test_flag_threshold_is_strict(montant, flag):
    assert is_suspicious(Decimal(montant)) is flag


def test_sums_on_small_sample():
    txs = parse_rows([
        row("10", iban_origine="A", banque_source="B1", iban_destinataire="X"),
        row("5.5", iban_origine="A", banque_source="B2", iban_destinataire="Y"),
        row("1", iban_origine="Z", banque_source="B1", iban_destinataire="X"),
    ])
    assert sum_sent_by_iban(txs) == {"A": Decimal("15.5"), "Z": Decimal("1")}
    assert sum_sent_by_bank(txs) == {"B1": Decimal("11"), "B2": Decimal("5.5")}
    assert sum_received_by_iban(txs) == {"X": Decimal("11"), "Y": Decimal("5.5")}


def test_flag_transactions_is_pure():
    txs = parse_rows([row("6000"), row("10")])
    flagged = flag_transactions(txs)
    assert [t.is_flagged for t in flagged] == [True, False]
    assert all(not t.is_flagged for t in txs)  # entrée non modifiée


def test_full_dataset_matches_expected():
    result = process(all_rows())
    assert len(result.transactions) == expected.TOTAL_TRANSACTIONS
    assert result.sent_by_iban == expected.SENT_BY_IBAN
    assert result.sent_by_bank == expected.SENT_BY_BANK
    assert result.received_by_iban == expected.RECEIVED_BY_IBAN
    assert sorted(t.montant for t in result.transactions if t.is_flagged) \
        == expected.FLAGGED_AMOUNTS


@pytest.mark.parametrize("bad", [
    row("12O0.00"), row("-5"), row("0"), row(montant=""),
    row(datetime_transaction="hier"), row(iban_origine=""),
])
def test_invalid_rows_are_rejected(bad):
    with pytest.raises(InvalidTransaction):
        parse_rows([bad])
