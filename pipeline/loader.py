"""Fonctions de CHARGEMENT des données (effets de bord : disque, réseau).

Séparées volontairement des fonctions de traitement (processing.py).
- Niveau 1 : LocalSource lit un dossier du système de fichiers
- Niveau 2 : S3Source lit un bucket S3 (SeaweedFS en local), avec retry
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from . import config, extractors, faults
from .retry import retry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawFile:
    key: str        # identifiant unique du fichier (nom ou clé S3)
    content: bytes

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def rows(self) -> List[Dict[str, str]]:
        # CSV, image (OCR) ou texte brut (SLM) -> lignes au format CSV
        return extractors.extract_rows(self.key, self.content)


class LocalSource:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def list_keys(self) -> List[str]:
        return sorted(p.name for p in self.directory.iterdir()
                      if p.is_file() and extractors.is_supported(p.name))

    def fetch(self, key: str) -> RawFile:
        return RawFile(key=key, content=(self.directory / key).read_bytes())


def s3_client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        # endpoint vide = vrai S3 AWS ; clés vides = rôle IAM de la VM (Terraform)
        endpoint_url=config.S3_ENDPOINT or None,
        aws_access_key_id=config.S3_ACCESS_KEY or None,
        aws_secret_access_key=config.S3_SECRET_KEY or None,
        region_name=config.S3_REGION,
        # on désactive les retries internes de boto3 pour que notre
        # mécanisme de retry soit visible et maîtrisé
        config=Config(retries={"max_attempts": 1}, connect_timeout=3, read_timeout=10),
    )


def _transient_s3_errors():
    from botocore.exceptions import ConnectionError as BotoConnectionError
    from botocore.exceptions import EndpointConnectionError, ReadTimeoutError

    return (faults.SimulatedFailure, BotoConnectionError, EndpointConnectionError,
            ReadTimeoutError, ConnectionError)


class S3Source:
    def __init__(self, bucket: str = None, prefix: str = None, client=None):
        self.bucket = bucket or config.S3_BUCKET
        self.prefix = prefix if prefix is not None else config.S3_PREFIX
        self.client = client or s3_client()

    def list_keys(self) -> List[str]:
        keys: List[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            keys += [o["Key"] for o in page.get("Contents", []) if extractors.is_supported(o["Key"])]
        return sorted(keys)

    def fetch(self, key: str) -> RawFile:
        return _fetch_with_retry(self.client, self.bucket, key)


@retry(exceptions=_transient_s3_errors(), attempts=config.RETRY_ATTEMPTS,
       base_delay=config.RETRY_BASE_DELAY)
def _fetch_with_retry(client, bucket: str, key: str) -> RawFile:
    """Niveau 2.4 - retry si la récupération du fichier échoue."""
    log.info("téléchargement s3://%s/%s", bucket, key)
    faults.maybe_fail("S3_GET")
    obj = client.get_object(Bucket=bucket, Key=key)
    return RawFile(key=key, content=obj["Body"].read())


def ensure_bucket(client, bucket: str) -> None:
    from botocore.exceptions import ClientError

    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)


def upload_directory(directory: str | Path, client=None, bucket: str = None,
                     prefix: str = None) -> List[str]:
    """Niveau 2.2 - dépose les fichiers générés (CSV, images, textes) dans le S3."""
    client = client or s3_client()
    bucket = bucket or config.S3_BUCKET
    prefix = prefix if prefix is not None else config.S3_PREFIX
    ensure_bucket(client, bucket)
    keys = []
    for path in sorted(Path(directory).iterdir()):
        if not extractors.is_supported(path.name):
            continue
        key = f"{prefix}{path.name}"
        client.put_object(Bucket=bucket, Key=key, Body=path.read_bytes())
        log.info("upload %s -> s3://%s/%s", path, bucket, key)
        keys.append(key)
    return keys
