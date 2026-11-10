"""Orchestration de la pipeline + CLI.

  python -m pipeline generate --out data/
  python -m pipeline upload   --dir data/            (Niveau 2)
  python -m pipeline init-db
  python -m pipeline process  --source local --dir data/
  python -m pipeline process  --source s3 [--loop --interval 60]   (Niveau 2/3)
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Dict

from . import config, db, generate, generate_extra, loader
from .processing import InvalidTransaction, process

log = logging.getLogger("pipeline")


def run_once(source, dsn: str) -> Dict[str, int]:
    """Traite tous les fichiers non encore traités de la source."""
    stats = {"processed": 0, "skipped": 0, "failed": 0}
    conn = db.connect(dsn)
    try:
        db.init_schema(conn)
        for key in source.list_keys():
            raw = source.fetch(key)
            if db.is_processed(conn, raw.key, raw.checksum):
                log.info("%s : déjà traité -> ignoré", key)
                stats["skipped"] += 1
                continue
            try:
                result = process(raw.rows())
            except InvalidTransaction as exc:
                log.error("%s : fichier invalide, non inséré (%s)", key, exc)
                stats["failed"] += 1
                continue
            try:
                db.insert_results(dsn, raw.key, raw.checksum, result)
                stats["processed"] += 1
            except db.AlreadyProcessed:
                log.info("%s : traité entre-temps par un autre worker", key)
                stats["skipped"] += 1
    finally:
        conn.close()
    log.info("bilan : %s", stats)
    return stats


def _make_source(args):
    if args.source == "local":
        return loader.LocalSource(args.dir)
    return loader.S3Source()


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s")
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("generate", help="génère les fichiers de test")
    p.add_argument("--out", default="data")
    p.add_argument("--no-images", action="store_true", help="sans relevé image (OCR)")
    p.add_argument("--texts", action="store_true", help="avec texte brut (SLM)")

    p = sub.add_parser("upload", help="dépose les CSV dans le S3")
    p.add_argument("--dir", default="data")

    sub.add_parser("init-db", help="crée le schéma")

    p = sub.add_parser("process", help="traite les fichiers et insère en base")
    p.add_argument("--source", choices=["local", "s3"], default="s3")
    p.add_argument("--dir", default="data")
    p.add_argument("--loop", action="store_true", help="tourne en continu (prod)")
    p.add_argument("--interval", type=int, default=60)

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        paths = generate.generate(args.out)
        if not args.no_images:
            paths += generate_extra.generate_images(args.out)
        if args.texts:
            paths += generate_extra.generate_texts(args.out)
        for path in paths:
            log.info("généré %s", path)
    elif args.cmd == "upload":
        loader.upload_directory(args.dir)
    elif args.cmd == "init-db":
        conn = db.connect()
        db.init_schema(conn)
        conn.close()
    elif args.cmd == "process":
        while True:
            stats = run_once(_make_source(args), config.DATABASE_URL)
            if not args.loop:
                return 1 if stats["failed"] else 0
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
