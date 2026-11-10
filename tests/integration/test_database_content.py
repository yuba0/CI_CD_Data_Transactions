"""Niveau 1.5 - Test d'intégration : vérifie l'état de la base APRÈS la pipeline.

À lancer une fois les étapes generate -> upload -> process exécutées
sur une base vide (c'est ce que fait la CI). Contenu attendu : 3 CSV + 1 image (OCR).
"""
from decimal import Decimal

import psycopg2
import pytest

from pipeline import config
from tests import expected


@pytest.fixture(scope="module")
def cur():
    conn = psycopg2.connect(config.DATABASE_URL)
    yield conn.cursor()
    conn.close()


def as_dict(cur, sql):
    cur.execute(sql)
    return {k: Decimal(v) for k, v in cur.fetchall()}


def test_every_file_processed_exactly_once(cur):
    cur.execute("SELECT file_key, row_count FROM processed_files")
    got = {k.rsplit("/", 1)[-1]: n for k, n in cur.fetchall()}
    assert got == expected.PIPELINE_FILES


def test_transaction_count_and_total(cur):
    cur.execute("SELECT COUNT(*), SUM(montant) FROM transactions")
    count, total = cur.fetchone()
    assert count == expected.PIPELINE_TOTAL_TRANSACTIONS
    assert total == expected.PIPELINE_TOTAL_AMOUNT


def test_no_duplicate_transactions(cur):
    cur.execute("""SELECT COUNT(*) FROM (
        SELECT datetime_transaction, iban_origine, montant FROM transactions
        GROUP BY 1, 2, 3 HAVING COUNT(*) > 1) d""")
    assert cur.fetchone()[0] == 0


def test_sent_by_iban(cur):
    assert as_dict(cur, "SELECT iban, total FROM v_total_sent_by_iban") \
        == expected.PIPELINE_SENT_BY_IBAN


def test_sent_by_bank(cur):
    assert as_dict(cur, "SELECT bank, total FROM v_total_sent_by_bank") \
        == expected.PIPELINE_SENT_BY_BANK


def test_received_by_iban(cur):
    assert as_dict(cur, "SELECT iban, total FROM v_total_received_by_iban") \
        == expected.PIPELINE_RECEIVED_BY_IBAN


def test_flagged_transactions(cur):
    cur.execute("SELECT montant FROM v_flagged_transactions ORDER BY montant")
    assert [r[0] for r in cur.fetchall()] == expected.PIPELINE_FLAGGED_AMOUNTS
    cur.execute("SELECT COUNT(*) FROM transactions WHERE montant > 5000 AND NOT is_flagged")
    assert cur.fetchone()[0] == 0
