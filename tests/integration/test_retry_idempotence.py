"""Niveaux 1.7 / 2.4 - Pannes simulées : le retry réussit SANS doublon.

Chaque test travaille dans sa propre base jetable pour ne pas polluer
la base vérifiée par test_database_content.py.
"""
import uuid
from urllib.parse import urlparse, urlunparse

import psycopg2
import pytest

from pipeline import config, faults, generate, loader
from pipeline.main import run_once
from tests import expected


@pytest.fixture
def dsn():
    name = f"test_{uuid.uuid4().hex[:8]}"
    admin = psycopg2.connect(config.DATABASE_URL)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {name}")
    url = urlparse(config.DATABASE_URL)
    yield urlunparse(url._replace(path=f"/{name}"))
    admin.cursor().execute(f"DROP DATABASE {name} WITH (FORCE)")
    admin.close()


@pytest.fixture(autouse=True)
def clean_faults(monkeypatch):
    faults.reset()
    yield
    faults.reset()


def count(dsn, sql):
    conn = psycopg2.connect(dsn)
    with conn.cursor() as c:
        c.execute(sql)
        n = c.fetchone()[0]
    conn.close()
    return n


def test_insert_retry_does_not_duplicate(dsn, tmp_path, monkeypatch):
    generate.generate(tmp_path)
    # les 2 premières insertions plantent APRÈS avoir écrit des lignes
    monkeypatch.setenv("FAIL_INSERT_TIMES", "2")

    stats = run_once(loader.LocalSource(tmp_path), dsn)

    assert stats == {"processed": 3, "skipped": 0, "failed": 0}
    assert count(dsn, "SELECT COUNT(*) FROM transactions") == expected.TOTAL_TRANSACTIONS
    assert count(dsn, "SELECT COUNT(*) FROM processed_files") == 3


def test_rerun_skips_already_processed_files(dsn, tmp_path):
    generate.generate(tmp_path)
    run_once(loader.LocalSource(tmp_path), dsn)

    stats = run_once(loader.LocalSource(tmp_path), dsn)

    assert stats == {"processed": 0, "skipped": 3, "failed": 0}
    assert count(dsn, "SELECT COUNT(*) FROM transactions") == expected.TOTAL_TRANSACTIONS


def test_renamed_copy_of_a_file_is_skipped(dsn, tmp_path):
    generate.generate(tmp_path)
    run_once(loader.LocalSource(tmp_path), dsn)
    (tmp_path / "copie.csv").write_bytes((tmp_path / "transactions_2026-01-01.csv").read_bytes())

    stats = run_once(loader.LocalSource(tmp_path), dsn)

    assert stats["processed"] == 0  # même checksum -> ignoré
    assert count(dsn, "SELECT COUNT(*) FROM transactions") == expected.TOTAL_TRANSACTIONS


def test_s3_download_retry(dsn, monkeypatch):
    client = loader.s3_client()
    bucket = f"retry-{uuid.uuid4().hex[:8]}"
    loader.ensure_bucket(client, bucket)
    client.put_object(Bucket=bucket, Key="incoming/t.csv",
                      Body=(_one_file_csv()).encode())
    monkeypatch.setenv("FAIL_S3_GET_TIMES", "2")

    stats = run_once(loader.S3Source(bucket=bucket, prefix="incoming/", client=client), dsn)

    assert stats["processed"] == 1
    assert count(dsn, "SELECT COUNT(*) FROM transactions") == 5


def _one_file_csv():
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=generate.COLUMNS)
    w.writeheader()
    w.writerows(generate.build_rows(generate.DATASET["transactions_2026-01-01.csv"]))
    return buf.getvalue()
