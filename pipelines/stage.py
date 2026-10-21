
"""Exécute une étape du projet (python -m src.<étape>) pour un orchestrateur.

Une étape possède des entrées, une commande et des sorties.
Elle tourne dans un dossier temporaire reproduisant l'arborescence du projet.

Kubeflow utilise run_stage().
Airflow utilise la commande python -m pipelines.stage avec --workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRS = ("data", "models", "reports")
XCOM_FILE = Path("/airflow/xcom/return.json")


def copy(src: str | Path, dst: str | Path) -> None:
    """Copie un fichier ou un dossier en créant les dossiers parents."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copyfile(src, dst)


def execute(
    module: str,
    args,
    workdir: Path,
    env: dict | None = None,
) -> None:
    """Lance python -m <module> dans le dossier de travail."""
    shutil.copyfile(ROOT / "params.yaml", workdir / "params.yaml")

    run_env = {**os.environ, **(env or {})}
    run_env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(ROOT), os.getenv("PYTHONPATH")])
    )

    config = Path(
        os.getenv("DATASET_CONFIG", ROOT / "dataset.yaml")
    ).resolve()
    run_env["DATASET_CONFIG"] = str(config)

    cmd = [sys.executable, "-m", module, *map(str, args)]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=workdir, env=run_env, check=True)


def run_stage(
    module: str,
    args=(),
    inputs=None,
    outputs=None,
    env=None,
) -> None:
    """Copie les entrées, exécute l'étape et récupère les sorties.

    inputs : {chemin relatif au projet : fichier ou dossier source}
    outputs : {chemin relatif au projet : destination de sortie}
    env : variables d'environnement supplémentaires
    """
    with tempfile.TemporaryDirectory(prefix="stage-") as tmp:
        work = Path(tmp)

        for rel, src in (inputs or {}).items():
            copy(src, work / rel)

        execute(module, args, work, env)

        for rel, dst in (outputs or {}).items():
            copy(work / rel, dst)


# --- Airflow : espace de travail local ou S3 --------------------


def _s3(workspace: str):
    """Retourne le client S3, le bucket et le préfixe."""
    import boto3

    bucket, _, prefix = workspace.removeprefix("s3://").partition("/")
    prefix = re.sub(r"[^A-Za-z0-9._/-]", "_", prefix).strip("/")
    return boto3.client("s3"), bucket, prefix


def pull(workspace: str, work: Path) -> None:
    """Récupère les fichiers des étapes précédentes."""
    if not workspace.startswith("s3://"):
        source = Path(workspace)
        if source.is_dir():
            copy(source, work)
        return

    s3, bucket, prefix = _s3(workspace)

    buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    if bucket not in buckets:
        s3.create_bucket(Bucket=bucket)

    for page in s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket,
        Prefix=f"{prefix}/",
    ):
        for obj in page.get("Contents", []):
            target = work / obj["Key"].removeprefix(f"{prefix}/")
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, obj["Key"], str(target))


def snapshot(work: Path) -> dict[Path, int]:
    """Retourne les fichiers de sortie et leurs dates de modification."""
    return {
        p: p.stat().st_mtime_ns
        for directory in OUTPUT_DIRS
        for p in (work / directory).rglob("*")
        if p.is_file()
    }


def push(
    work: Path,
    workspace: str,
    before: dict[Path, int],
) -> None:
    """Publie les fichiers créés ou modifiés par l'étape."""
    changed = [
        p
        for p, mtime in snapshot(work).items()
        if before.get(p) != mtime
    ]

    if workspace.startswith("s3://"):
        s3, bucket, prefix = _s3(workspace)
        for path in changed:
            key = f"{prefix}/{path.relative_to(work).as_posix()}"
            s3.upload_file(str(path), bucket, key)
    else:
        destination = Path(workspace)
        for path in changed:
            copy(path, destination / path.relative_to(work))

    print(
        f"{len(changed)} fichier(s) publié(s) dans {workspace}",
        flush=True,
    )


def xcom_summary(work: Path) -> dict:
    """Prépare les petites valeurs utiles aux tâches Airflow suivantes."""
    from mlflow.models import Model

    from src.evaluate import METRICS_JSON
    from src.train import MODEL_DIR

    summary = {}

    model_path = work / MODEL_DIR
    if (model_path / "MLmodel").exists():
        summary["mlflow_run_id"] = Model.load(
            str(model_path)
        ).metadata["mlflow_run_id"]

    metrics_path = work / METRICS_JSON
    if metrics_path.exists():
        summary["metrics"] = json.loads(
            metrics_path.read_text(encoding="utf-8")
        )

    return summary


def main() -> None:
    """Point d'entrée en ligne de commande pour Airflow."""
    parser = argparse.ArgumentParser(
        description="Exécute une étape du projet (task Airflow)",
        allow_abbrev=False,
    )
    parser.add_argument(
        "module",
        help="Étape à lancer, par exemple src.prepare",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="s3://bucket/préfixe ou chemin d'un dossier local",
    )
    parser.add_argument(
        "--xcom",
        action="store_true",
        help=f"Écrit un résumé dans {XCOM_FILE}",
    )

    opts, args = parser.parse_known_args()
    args = [arg for arg in args if arg != "--"]

    with tempfile.TemporaryDirectory(prefix="stage-") as tmp:
        work = Path(tmp)
        pull(opts.workspace, work)
        before = snapshot(work)
        execute(opts.module, args, work)
        push(work, opts.workspace, before)

        if opts.xcom:
            summary = xcom_summary(work)
            XCOM_FILE.parent.mkdir(parents=True, exist_ok=True)
            XCOM_FILE.write_text(
                json.dumps(summary),
                encoding="utf-8",
            )
            print("XCom :", summary, flush=True)


if __name__ == "__main__":
    main()
