# Image de serving optimisée. Contexte de build = RACINE du repo :
# docker build -f packaging/Dockerfile -t scoring-api:optimized .

# --- Stage 1 : builder — installe les dépendances dans /deps ---
FROM python:3.12-slim AS builder
WORKDIR /build
COPY packaging/requirements.txt .
RUN pip install --no-cache-dir --target=/deps -r requirements.txt \
 && find /deps -type d -name __pycache__ -prune -exec rm -rf {} + \
 && rm -rf /deps/pandas/tests \
 && find /deps/numpy -type d -name tests -prune -exec rm -rf {} +

# --- Stage 2 : runtime — uniquement ce qui sert à répondre aux requêtes ---
FROM python:3.12-slim AS runtime

# UID fixe : Kubernetes (runAsNonRoot) exige un USER numérique.
RUN groupadd --gid 10001 ml \
 && useradd --uid 10001 --gid ml --no-create-home --shell /usr/sbin/nologin ml

WORKDIR /app
COPY --from=builder /deps /deps
ENV PYTHONPATH=/deps \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY dataset.yaml ./
COPY src/__init__.py src/dataset_config.py src/
COPY packaging/app/__init__.py packaging/app/serve.py packaging/app/
# Le modèle change plus souvent que le code : dernière couche, pour profiter du cache.
COPY packaging/model/model.onnx packaging/model/metadata.json packaging/model/

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --start-interval=2s \
  CMD ["python", "-c", \
       "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

ARG VERSION=1.0.0
ARG MODEL_VERSION=unknown
LABEL org.opencontainers.image.title="scoring-api" \
      org.opencontainers.image.version="${VERSION}" \
      mlflow.model_name="scoring-model" \
      mlflow.model_alias="champion" \
      mlflow.model_version="${MODEL_VERSION}"

# Lab 5 : l'API connaît la version de son image (/version, /metadata) — canary, rollback.
ENV APP_VERSION=${VERSION}

CMD ["python", "-m", "uvicorn", "app.serve:app", "--app-dir", "packaging", \
     "--host", "0.0.0.0", "--port", "8000"]
