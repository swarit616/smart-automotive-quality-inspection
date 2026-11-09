# Model weights

Place trained weights here (they are not committed):

| File | Used when |
|---|---|
| `best.onnx` + `class_names.json` | served with ONNX Runtime (CPU-friendly, no PyTorch needed) |
| `best.pt` | served with Ultralytics (needs `requirements-train.txt`) |
| `metrics.json` | written by `python -m ml.evaluate`; shown in the dashboard only for real models |
| `training_status.json` | written by `python -m ml.train` |

Without weights the application runs in DEMO MODE and says so everywhere. See `docs/MODEL_TRAINING.md`.
