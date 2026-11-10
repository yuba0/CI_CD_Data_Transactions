"""Niveau 3 - Extraction de transactions depuis du texte brut par un SLM (Ollama).

Nécessite Ollama + le modèle (job `slm` de la CI). En local, ces tests sont
ignorés si Ollama n'est pas joignable, sauf si REQUIRE_SLM=1.
"""
import os
import urllib.request
from datetime import datetime

import pytest

from pipeline import config, generate_extra
from pipeline.extractors import extract_rows
from pipeline.processing import process
from tests import expected


def _ollama_up() -> bool:
    try:
        urllib.request.urlopen(f"{config.OLLAMA_URL}/api/tags", timeout=2)
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_up() and os.getenv("REQUIRE_SLM") != "1",
    reason="Ollama non joignable",
)


@pytest.fixture(scope="module")
def transactions(tmp_path_factory):
    out = tmp_path_factory.mktemp("slm")
    [path] = generate_extra.generate_texts(out)
    return process(extract_rows(path.name, path.read_bytes())).transactions


def test_slm_extracts_every_transaction(transactions):
    got = [
        (t.datetime_transaction, t.iban_origine, t.pays_source, t.banque_source,
         t.iban_destinataire, t.pays_destinataire, t.montant, t.is_flagged)
        for t in transactions
    ]
    want = [(datetime.fromisoformat(e[0]),) + e[1:] for e in expected.TEXT_TRANSACTIONS]
    assert got == want
