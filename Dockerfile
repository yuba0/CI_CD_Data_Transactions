FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
# Tesseract : OCR des relevés en image (Niveau 3)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pipeline/ pipeline/
COPY sql/ sql/
RUN useradd --create-home app
USER app
# Mode production : vérifie le S3 toutes les PROCESS_INTERVAL secondes
CMD ["sh", "-c", "python -m pipeline process --source s3 --loop --interval ${PROCESS_INTERVAL:-60}"]
