
FROM python:3.12-slim

WORKDIR /app

# Installer les dépendances du projet
COPY pipelines/requirements.txt /tmp/requirements.txt

RUN pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt \
    && pip install --no-cache-dir --root-user-action=ignore --no-deps kfp==2.17.0

# Copier le code et les fichiers de configuration
COPY dataset.yaml params.yaml ./
COPY src/ src/
COPY pipelines/__init__.py pipelines/stage.py pipelines/

ENV PYTHONPATH=/app \
    DATASET_CONFIG=/app/dataset.yaml \
    PYTHONUNBUFFERED=1

ARG VERSION=dev

LABEL org.opencontainers.image.title="scoring-pipeline" \
      org.opencontainers.image.version="${VERSION}"
