"""Test de charge de l'InferenceService (Lab 5) — rejoue de vraies lignes de test.csv.

Variables d'environnement : ISVC_HOST, API_FORMAT (v1|v2), V2_MODEL, BATCH_SIZE.
"""

import os
import random

from locust import HttpUser, between, task
from payloads import complete_rows, load_rows, v1_body, v2_body

ISVC_HOST = os.getenv("ISVC_HOST", "")
API_FORMAT = os.getenv("API_FORMAT", "v1")
V2_MODEL = os.getenv("V2_MODEL", "scoring-model")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))
ROWS = load_rows() if API_FORMAT == "v1" else complete_rows(load_rows())


class PredictUser(HttpUser):
    wait_time = between(0.1, 0.3)

    def on_start(self):
        if ISVC_HOST:
            self.client.headers["Host"] = ISVC_HOST

    @task
    def predict(self):
        rows = random.choices(ROWS, k=BATCH_SIZE)
        if API_FORMAT == "v2":
            self.client.post(
                f"/v2/models/{V2_MODEL}/infer", json=v2_body(rows), name="/v2/models/[model]/infer"
            )
        else:
            self.client.post("/predict", json=v1_body(rows))
