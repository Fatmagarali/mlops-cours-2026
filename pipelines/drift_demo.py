"""Démonstration de drift : nouvelle clientèle comparée à celle d'entraînement."""

from pathlib import Path

import yaml
from kfp import compiler, dsl
from kfp.dsl import Dataset, Input, Output

from pipelines.components import PIPELINE_IMAGE, detect_drift, ingest_data, prepare_features

DRIFT = yaml.safe_load(Path("params.yaml").read_text(encoding="utf-8"))["drift"]


@dsl.component(base_image=PIPELINE_IMAGE, install_kfp_package=False)
def simulate_drift(data: Input[Dataset], drifted: Output[Dataset]) -> None:
    from pipelines.stage import run_stage

    clean, shifted = "data/drift/clean.csv", "data/drift/drifted.csv"
    run_stage(
        "src.simulate",
        args=["drift", clean, shifted],
        inputs={clean: data.path},
        outputs={shifted: drifted.path},
    )


@dsl.pipeline(name="scoring-drift-demo", description="Drift simulé détecté par detect_drift")
def drift_pipeline(
    ks_alpha: float = DRIFT["ks_alpha"],
    psi_threshold: float = DRIFT["psi_threshold"],
    drift_share: float = DRIFT["drift_share"],
    fail_on_drift: bool = False,
):
    ingest_task = ingest_data()
    prep_task = prepare_features(raw_data=ingest_task.outputs["raw_data"])
    drifted_task = simulate_drift(data=prep_task.outputs["test_data"])
    drift_task = detect_drift(
        reference_data=prep_task.outputs["train_data"],
        current_data=drifted_task.outputs["drifted"],
        ks_alpha=ks_alpha,
        psi_threshold=psi_threshold,
        drift_share=drift_share,
        fail_on_drift=fail_on_drift,
    )
    drift_task.set_memory_limit("1Gi")


if __name__ == "__main__":
    compiler.Compiler().compile(drift_pipeline, package_path="drift_demo.yaml")
