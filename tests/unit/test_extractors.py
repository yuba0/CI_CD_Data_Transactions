"""Tests des parseurs OCR / SLM (fonctions pures, sans Tesseract ni Ollama)."""
import json

import pytest

from pipeline import extractors
from pipeline.generate_extra import TEXT_DATASET, render_text
from pipeline.processing import InvalidTransaction

# Sortie réelle de Tesseract sur releve_2026-01-04.png (espaces parasites inclus)
OCR_SAMPLE = """RELEVE DE VIREMENTS

2026-01-04 09:00:00 ; FR7610001000010000000000001 ; FR; Banque Alpha ; DE89370400440532013000 ; DE ; 1500.00
2026-01-04 10:15:00 ; DE89370400440532013000 ; DE ; Banque Gamma; IT60X05428111010000001 23456 ; IT ; 9100.00
"""


def test_ocr_text_is_parsed_and_cleaned():
    rows = extractors.parse_ocr_text(OCR_SAMPLE)
    assert len(rows) == 2
    assert rows[1] == {
        "datetime_transaction": "2026-01-04T10:15:00",
        "iban_origine": "DE89370400440532013000",
        "pays_source": "DE",
        "banque_source": "Banque Gamma",
        "iban_destinataire": "IT60X0542811101000000123456",  # espace supprimé
        "pays_destinataire": "IT",
        "montant": "9100.00",
    }


def test_ocr_with_missing_column_is_rejected():
    with pytest.raises(InvalidTransaction):
        extractors.parse_ocr_text("2026-01-04 09:00:00 ; FR76100 ; FR ; 1500.00")


def test_ocr_without_transaction_is_rejected():
    with pytest.raises(InvalidTransaction):
        extractors.parse_ocr_text("RELEVE DE VIREMENTS\n\n")


def _answer(**overrides):
    tx = {
        "datetime_transaction": "2026-01-05T08:30:00",
        "iban_origine": "FR7610002000020000000000002", "pays_source": "fr",
        "banque_source": "Banque Beta", "iban_destinataire": "ES9121000418450200051332",
        "pays_destinataire": "ES", "montant": "2750,00",
    }
    tx.update(overrides)
    return json.dumps({"transactions": [tx]})


SOURCE = render_text(TEXT_DATASET["message_2026-01-05.txt"])


def test_slm_answer_is_normalised():
    [row] = extractors.parse_slm_answer(_answer(), SOURCE)
    assert row["pays_source"] == "FR"
    assert row["montant"] == "2750.00"


@pytest.mark.parametrize("bad", [
    _answer(iban_origine="FR7699999999999999999999999"),  # IBAN inventé
    _answer(montant="9999.00"),                            # montant inventé
    _answer(pays_destinataire="Espagne"),                  # pas un code ISO
    "pas du json",
    json.dumps({"transactions": []}),
])
def test_slm_hallucinations_are_rejected(bad):
    with pytest.raises(InvalidTransaction):
        extractors.parse_slm_answer(bad, SOURCE)


def test_dispatch_by_extension():
    assert extractors.is_supported("incoming/a.CSV")
    assert extractors.is_supported("b.png") and extractors.is_supported("c.txt")
    assert not extractors.is_supported("notes.pdf")
