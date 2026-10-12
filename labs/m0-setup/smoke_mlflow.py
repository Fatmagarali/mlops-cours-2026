"""Smoke test MLflow : logge un run (paramètre, métriques, artefact) sur le serveur."""
import os
import mlflow

mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000"))
mlflow.set_experiment("smoke-test")

with mlflow.start_run(run_name="hello-mlops") as run:
    mlflow.log_param("framework", "scikit-learn")
    mlflow.log_metric("accuracy", 0.42)
    mlflow.log_metric("loss", 1.337)
    mlflow.log_text("hello mlops\n", "hello.txt")
    print("Run logged successfully.")
    print(f"run_id : {run.info.run_id}")
    print(f"artifact_uri : {run.info.artifact_uri}")
