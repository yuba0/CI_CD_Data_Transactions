"""Configuration via variables d'environnement (12-factor)."""
import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://pipeline:pipeline@localhost:5433/transactions"
)

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:8333")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "pipeline")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "pipeline-secret")
S3_BUCKET = os.getenv("S3_BUCKET", "transactions")
S3_PREFIX = os.getenv("S3_PREFIX", "incoming/")
S3_REGION = os.getenv("S3_REGION", "us-east-1")

RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "5"))
RETRY_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY", "0.5"))

# Niveau 3 - petit modèle de langage (Ollama)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
SLM_MODEL = os.getenv("SLM_MODEL", "qwen2.5:1.5b")
SLM_TIMEOUT = float(os.getenv("SLM_TIMEOUT", "300"))
