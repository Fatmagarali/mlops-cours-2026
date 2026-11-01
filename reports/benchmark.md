# Benchmark de latence — german-credit, modèle v9

1000 appels par backend, après 10 appels de chauffe · x86_64 · Python 3.12.15

| Backend | P50 (ms) | P95 (ms) | P99 (ms) |
|---|---|---|---|
| sklearn_pipeline | 7.588 | 10.845 | 14.008 |
| onnx_python | 0.108 | 0.248 | 0.378 |
| onnx_batch_100 | 0.517 | 0.890 | 1.311 |

Accélération ONNX vs scikit-learn (P50, 1 ligne) : x70.4
