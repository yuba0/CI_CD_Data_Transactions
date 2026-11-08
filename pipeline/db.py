"""Niveau 1.3 / 1.7 - Accès base de données : schéma, insertion, retry.

Garanties contre le double traitement :
1. Avant traitement, on vérifie dans `processed_files` si la clé OU le
   checksum du fichier est déjà connu -> le fichier est ignoré.
2. Toute l'insertion d'un fichier (registre + transactions + agrégats) se
   fait dans UNE transaction SQL. Si une erreur survient au milieu, ROLLBACK :
   rien n'est écrit, et le retry repart d'un état propre.
3. Les contraintes PRIMARY KEY / UNIQUE empêchent physiquement les doublons
   même en cas d'exécutions concurrentes.
"""
from __future__ import annotations

import logging
from pathlib import Path

import psycopg2
import psycopg2.extras

from . import config, faults
from .processing import ProcessingResult
from .retry import retry

log = logging.getLogger(__name__)

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"

TRANSIENT_DB_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError,
                       faults.SimulatedFailure)


class AlreadyProcessed(Exception):
    pass


@retry(exceptions=(psycopg2.OperationalError,), attempts=10, base_delay=1, max_delay=3)
def connect(dsn: str = None):
    """Connexion avec retry : la base peut mettre quelques secondes à démarrer."""
    return psycopg2.connect(dsn or config.DATABASE_URL)


def init_schema(conn) -> None:
    with conn, conn.cursor() as cur:
        cur.execute(SCHEMA_FILE.read_text())
    log.info("schéma initialisé")


def is_processed(conn, file_key: str, checksum: str) -> bool:
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM processed_files WHERE file_key = %s OR checksum = %s",
            (file_key, checksum),
        )
        return cur.fetchone() is not None


def _insert_file(conn, file_key: str, checksum: str, result: ProcessingResult) -> None:
    """Insertion atomique : tout ou rien."""
    with conn:  # BEGIN ... COMMIT (ou ROLLBACK si exception)
        with conn.cursor() as cur:
            # ON CONFLICT DO NOTHING + rowcount : protège contre un 2e worker
            cur.execute(
                """INSERT INTO processed_files (file_key, checksum, row_count)
                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                (file_key, checksum, len(result.transactions)),
            )
            if cur.rowcount == 0:
                raise AlreadyProcessed(file_key)

            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO transactions (file_key, line_number, datetime_transaction,
                   iban_origine, pays_source, banque_source, iban_destinataire,
                   pays_destinataire, montant, is_flagged) VALUES %s""",
                [(file_key, t.line_number, t.datetime_transaction, t.iban_origine,
                  t.pays_source, t.banque_source, t.iban_destinataire,
                  t.pays_destinataire, t.montant, t.is_flagged)
                 for t in result.transactions],
            )

            # Point de panne simulée : APRÈS avoir écrit des lignes, AVANT le
            # commit -> démontre que le rollback évite les insertions partielles.
            faults.maybe_fail("INSERT")

            for table, col, data in (
                ("sent_by_iban", "iban", result.sent_by_iban),
                ("sent_by_bank", "bank", result.sent_by_bank),
                ("received_by_iban", "iban", result.received_by_iban),
            ):
                psycopg2.extras.execute_values(
                    cur,
                    f"INSERT INTO {table} (file_key, {col}, total) VALUES %s",
                    [(file_key, k, v) for k, v in data.items()],
                )


@retry(exceptions=TRANSIENT_DB_ERRORS, attempts=config.RETRY_ATTEMPTS,
       base_delay=config.RETRY_BASE_DELAY)
def insert_results(dsn: str, file_key: str, checksum: str, result: ProcessingResult) -> None:
    """Niveau 1.7 - insertion avec retry.

    Une nouvelle connexion est ouverte à chaque tentative (la précédente peut
    être morte). Grâce à la transaction, une tentative ratée ne laisse rien.
    """
    conn = psycopg2.connect(dsn)
    try:
        _insert_file(conn, file_key, checksum, result)
        log.info("%s : %d transactions insérées", file_key, len(result.transactions))
    finally:
        conn.close()
