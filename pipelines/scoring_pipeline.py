"""Pipeline KFP « scoring-pipeline » (Labs 2 et 3).

ingest -> validate_data -> prepare -> detect_drift -> train -> evaluate
       -> validate_model -> register
"""

from pathlib import Path

import yaml
from kfp import compiler, dsl, kubernetes

from pipelines.components import (
    MLFLOW_URI,
    detect_drift,
    evaluate_model,
    ingest_data,
    prepare_features,
    register_model,
    train_model,
    validate_data,
    validate_model,
)

PARAMS = yaml.safe_load(Path("params.yaml").read_text(encoding="utf-8"))
TRAIN, DRIFT = PARAMS["train"], PARAMS["drift"]


@dsl.pipeline(
    name="scoring-pipeline",
    description="Credit scoring : ingest -> validate -> prepare -> drift -> train -> evaluate"
    " -> validate_model -> register",
)
def scoring_pipeline(
    model_type: str = TRAIN["model"],
    C: float = TRAIN["C"],
    class_weight: str = str(TRAIN["class_weight"]),
    n_estimators: int = TRAIN["n_estimators"],
    max_depth: str = str(TRAIN["max_depth"]),
    learning_rate: float = TRAIN["learning_rate"],
    random_state: int = TRAIN["random_state"],
    mlflow_uri: str = MLFLOW_URI,
    ks_alpha: float = DRIFT["ks_alpha"],
    psi_threshold: float = DRIFT["psi_threshold"],
    drift_share: float = DRIFT["drift_share"],
):
    ingest_task = ingest_data()
    ingest_task.set_retry(num_retries=3, backoff_duration="30s")
    ingest_task.set_cpu_limit("500m").set_memory_limit("512Mi")
    kubernetes.set_timeout(ingest_task, 600)

    # Gate 1 : contrat de données
    validate_task = validate_data(raw_data=ingest_task.outputs["raw_data"])
    validate_task.set_memory_limit("1Gi")

    prep_task = prepare_features(raw_data=ingest_task.outputs["raw_data"])
    prep_task.after(validate_task)
    prep_task.set_memory_limit("1Gi")

    # Gate 2 : drift train vs test
    drift_task = detect_drift(
        reference_data=prep_task.outputs["train_data"],
        current_data=prep_task.outputs["test_data"],
        ks_alpha=ks_alpha,
        psi_threshold=psi_threshold,
        drift_share=drift_share,
        fail_on_drift=True,
    )
    drift_task.set_memory_limit("1Gi")

    train_task = train_model(
        raw_data=ingest_task.outputs["raw_data"],
        train_data=prep_task.outputs["train_data"],
        test_data=prep_task.outputs["test_data"],
        model_type=model_type,
        C=C,
        class_weight=class_weight,
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        random_state=random_state,
        mlflow_uri=mlflow_uri,
        kfp_run_id=dsl.PIPELINE_JOB_ID_PLACEHOLDER,
    )
    train_task.after(drift_task)
    train_task.set_cpu_request("500m").set_cpu_limit("2")
    train_task.set_memory_request("512Mi").set_memory_limit("2Gi")
    kubernetes.set_timeout(train_task, 1800)
    train_task.set_caching_options(enable_caching=False)

    eval_task = evaluate_model(
        model=train_task.outputs["model"],
        test_data=prep_task.outputs["test_data"],
        run_id=train_task.outputs["Output"],
        mlflow_uri=mlflow_uri,
    )
    eval_task.set_memory_limit("1Gi")

    # Gate 3 : validation du modèle
    model_task = validate_model(
        model=train_task.outputs["model"],
        train_data=prep_task.outputs["train_data"],
        test_data=prep_task.outputs["test_data"],
    )
    model_task.set_memory_limit("1Gi")

    register_task = register_model(run_id=train_task.outputs["Output"], mlflow_uri=mlflow_uri)
    register_task.after(eval_task, model_task)
    register_task.set_memory_limit("1Gi")


if __name__ == "__main__":
    compiler.Compiler().compile(scoring_pipeline, package_path="scoring_pipeline.yaml")
