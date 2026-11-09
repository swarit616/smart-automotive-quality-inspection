# Model training, evaluation and serving

**Status of this build:** training could not be run (no network, no GPU, Ultralytics/PyTorch not installable in the sandbox). The scripts are implemented but their Ultralytics-dependent paths were **not executed**. The surrounding logic (dataset validation, splitting, metric computation, evaluation loop) is unit-tested with the demo detector on synthetic data. No weights or metrics are included, and none are claimed.

## Requirements
```bash
pip install -r backend/requirements-train.txt     # ultralytics 8.3.50, torch 2.5.1 (CPU wheel is fine), matplotlib
```
Licence: **Ultralytics YOLOv8 is AGPL-3.0** (with a commercial enterprise licence available). Using it in a network service or commercial product has obligations; read them before deploying beyond a portfolio.

## Train / fine-tune
```bash
cd backend
python -m ml.train --data ../data/datasets/neu-det/data.yaml --model yolov8n.pt --epochs 50 --imgsz 640 --batch 8 --device auto
```
* Starts from COCO-pretrained `yolov8n.pt` (downloaded by Ultralytics on first use). That model is a *general object detector*; it is not a defect model until fine-tuned.
* CPU: use `yolov8n`, `--batch 4-8`, fewer epochs (expect hours). GPU is selected automatically (`--device auto`).
* Dataset validation runs first and stops training on errors or leakage (`--skip-validation` to bypass).
* Outputs: `runs/train/defects/...`, then `models/best.pt`, `models/class_names.json`, `models/training_status.json` (running/completed/failed + configuration; shown on the Model screen).

## Evaluate on held-out data
```bash
python -m ml.evaluate --weights ../models/best.pt --data ../data/datasets/neu-det --split test --conf 0.25
```
Computes, with the project's own implementation (`app/core/metrics.py`, unit-tested on hand-computed cases):
* precision, recall, F1 at `--conf` and IoU 0.5, overall and per class;
* AP per class with COCO-style 101-point interpolation, mAP@0.50 and mAP@0.50:0.95 (classes without ground truth are excluded from the mean);
* confusion matrix (rows = true, columns = predicted, last = background) and an optional PNG.
It refuses to run without a non-empty held-out split. It writes `models/metrics.json` including dataset path, split, image count, the weights hash and a `synthetic_dataset` flag. The dashboard shows metrics only if the file exists and the mode is `real`, and warns when the weights hash differs.

Numbers from Ultralytics' own `model.val()` will differ slightly (different interpolation/NMS details); do not mix the two in one report.

## Export for CPU serving
```bash
python -m ml.export_onnx --weights ../models/best.pt      # -> best.onnx + best.names.json
```
Then set `MODEL_WEIGHTS_PATH=models/best.onnx`. `OnnxYoloDetector` expects the standard YOLOv8 head `(1, 4+nc, N)`; its decoding/NMS/letterbox maths is unit-tested with synthetic tensors, but it has **not been run against a real exported model** in this build – run `python -m ml.infer <image> --mode real` after exporting to confirm.

## Interpreting results honestly
Report the dataset, split sizes, class balance, confidence threshold and per-class numbers. Small datasets give noisy mAP; the six NEU-DET classes are far easier than real production variation (lighting, part geometry, rare defects). State limitations in any write-up.
