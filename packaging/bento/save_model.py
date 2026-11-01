"""Étape 6.1 — copie le modèle MLflow exporté à l'étape 1 dans le model store BentoML."""

import json
import os
import sys
from pathlib import Path

import bentoml
import mlflow

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT))
from src.dataset_config import load_config  # noqa: E402

cfg = load_config(ROOT / "dataset.yaml")
meta = json.loads((ROOT / "packaging/model/metadata.json").read_text())

mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000"))
model = mlflow.sklearn.load_model(f"models:/{meta['model_name']}/{meta['model_version']}")

saved = bentoml.sklearn.save_model(
    "scoring_model",
    model,
    labels={"mlflow_model": meta["model_name"], "mlflow_version": meta["model_version"]},
    metadata={
        "dataset": cfg.name,
        "numeric": cfg.numeric,
        "categorical": cfg.categorical,
        "positive_class": str(cfg.positive_class),
        "threshold": meta["threshold"],
        "model_version": meta["model_version"],
    },
)
print(f"Saved to BentoML model store: {saved.tag}")
