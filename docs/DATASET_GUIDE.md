# Dataset guide

## What was (not) done in this build
The build sandbox had **no network access**, so no public dataset was downloaded and no licence could be verified online. Nothing in this repository is real defect data except what you add. The synthetic generator exists to exercise the pipeline.

## Recommended real dataset: NEU-DET
Hot-rolled steel strip surface defects, six classes: `crazing`, `inclusion`, `patches`, `pitted_surface`, `rolled-in_scale`, `scratches` (to my knowledge 1,800 grayscale images, 300 per class, 200×200 px, Pascal-VOC XML boxes - confirm against the copy you download). Released by the Northeastern University (Song & Yan, "A noise robust method based on completed local binary patterns for hot-rolled steel strip surface defects", Applied Surface Science, 2013).
* **Licence/terms: not verified here.** Obtain it from the authors' distribution page or a mirror, read the stated terms (it is commonly described as free for research use) and do not redistribute it inside this repository.
* **Intended use / caveat:** steel strip defects, not automotive parts specifically. For an "automotive" claim you need your own part images or a dataset of machined/painted automotive surfaces; describe the model honestly as a surface-defect detector trained on the dataset you used.
* Images are small and roughly class-balanced, so mAP numbers are not comparable to real production lines.

## Workflow
```bash
cd backend
# 1) convert VOC XML -> YOLO txt (flat folders)
python -m ml.dataset_tools voc2yolo --images /path/NEU-DET/IMAGES --annotations /path/NEU-DET/ANNOTATIONS \
    --out /tmp/neu_yolo --classes crazing inclusion patches pitted_surface rolled-in_scale scratches
# 2) split without leakage (identical images are grouped; stratified; deterministic with --seed)
python -m ml.dataset_tools split --images /tmp/neu_yolo/images --labels /tmp/neu_yolo/labels \
    --out ../data/datasets/neu-det --classes crazing inclusion patches pitted_surface rolled-in_scale scratches
# 3) validate
python -m ml.dataset_tools validate --root ../data/datasets/neu-det
```
The class list order defines class ids; keep it identical everywhere (it is written to `data.yaml`).

## What validation checks
Unreadable images; labels without images (orphans); missing labels (counted as background images); malformed lines; class ids outside the class list; coordinates outside [0,1] or boxes extending beyond the image; duplicate images; **identical images in different splits (leakage)**; class imbalance warnings.

## Your own images
Label with any tool that exports YOLO format (e.g. CVAT, Label Studio), put images/labels in two flat folders and run `split` + `validate`. Record the source, capture conditions and licence/consent in a `README.md` next to the dataset.

## Synthetic demonstration dataset
`python -m ml.dataset_tools synthetic --out ../data/datasets/synthetic-demo --count 240` renders scratches and pits on a synthetic brushed-metal texture and writes a `SYNTHETIC_DATASET` marker. `ml.evaluate` copies a warning into `metrics.json` when that marker is present and the dashboard repeats it. **Never present results on it as real-world performance.**

## Class imbalance
Check `class_counts` in the validation report. Real defect data is usually heavily imbalanced (rare defects). Mitigations: collect more rare-class images, per-class thresholds in the decision rules, and always report per-class precision/recall (not only mAP).
