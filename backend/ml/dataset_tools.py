"""Dataset tooling for YOLO-format detection datasets (no heavy dependencies).

Commands (run from backend/):
  python -m ml.dataset_tools validate  --root data/datasets/neu-det
  python -m ml.dataset_tools split     --images RAW/images --labels RAW/labels --out data/datasets/my-set --classes crazing inclusion ...
  python -m ml.dataset_tools voc2yolo  --images RAW/IMAGES --annotations RAW/ANNOTATIONS --out RAW_yolo --classes crazing inclusion patches pitted_surface rolled-in_scale scratches
  python -m ml.dataset_tools synthetic --out data/datasets/synthetic-demo --count 240
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import cv2

from app.core import synthetic
from app.core.boxes import BoxError, validate_yolo_box

IMG_EXT = {".jpg", ".jpeg", ".png"}
SPLITS = ("train", "val", "test")
SYNTHETIC_MARKER = "SYNTHETIC_DATASET"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()


def read_label_file(path: Path, num_classes: int) -> tuple[list[tuple[int, float, float, float, float]], list[str]]:
    rows, errors = [], []
    for ln, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            errors.append(f"{path.name}:{ln}: expected 5 values, found {len(parts)}")
            continue
        try:
            cid = int(parts[0])
            cx, cy, w, h = map(float, parts[1:])
        except ValueError:
            errors.append(f"{path.name}:{ln}: non-numeric value")
            continue
        if not 0 <= cid < num_classes:
            errors.append(f"{path.name}:{ln}: class id {cid} outside 0..{num_classes - 1}")
            continue
        try:
            validate_yolo_box(cx, cy, w, h)
        except BoxError as exc:
            errors.append(f"{path.name}:{ln}: {exc}")
            continue
        rows.append((cid, cx, cy, w, h))
    return rows, errors


def validate_yolo_dataset(root: Path, class_names: list[str] | None = None) -> dict:
    """Validate a dataset laid out as root/images/<split>/*.jpg and root/labels/<split>/*.txt.

    Checks: unreadable images, missing/orphan labels, malformed lines, class ids, box coordinates,
    duplicate images and (critically) identical images shared across splits (leakage).
    """
    root = Path(root)
    if class_names is None:
        meta = root / "data.yaml"
        class_names = _read_names(meta) if meta.is_file() else None
    if not class_names:
        raise ValueError("class names required: pass them or provide data.yaml with 'names'")
    report = {"root": str(root), "splits": {}, "errors": [], "warnings": [], "classes": class_names, "leakage": []}
    hashes: dict[str, list[str]] = defaultdict(list)
    class_counts = defaultdict(int)
    for split in SPLITS:
        img_dir, lbl_dir = root / "images" / split, root / "labels" / split
        if not img_dir.is_dir():
            if split == "train":
                report["errors"].append(f"missing {img_dir}")
            else:
                report["warnings"].append(f"split '{split}' not present")
            continue
        imgs = sorted(p for p in img_dir.iterdir() if p.suffix.lower() in IMG_EXT)
        n_boxes = n_bg = 0
        for img in imgs:
            if cv2.imread(str(img)) is None:
                report["errors"].append(f"{split}/{img.name}: unreadable image")
                continue
            hashes[sha256_file(img)].append(f"{split}/{img.name}")
            lbl = lbl_dir / (img.stem + ".txt")
            if not lbl.is_file():
                n_bg += 1  # no label file = background image (allowed, counted)
                continue
            rows, errs = read_label_file(lbl, len(class_names))
            report["errors"] += [f"{split}/{e}" for e in errs]
            if not rows:
                n_bg += 1
            for r in rows:
                class_counts[class_names[r[0]]] += 1
            n_boxes += len(rows)
        stems = {p.stem for p in imgs}
        for lbl in (lbl_dir.glob("*.txt") if lbl_dir.is_dir() else []):
            if lbl.stem not in stems:
                report["errors"].append(f"{split}/{lbl.name}: label without image")
        report["splits"][split] = {"images": len(imgs), "boxes": n_boxes, "background_images": n_bg}
    for files in hashes.values():
        if len(files) > 1:
            splits_involved = {f.split("/")[0] for f in files}
            (report["leakage"] if len(splits_involved) > 1 else report["warnings"]).append(
                f"identical image content: {files}" if len(splits_involved) > 1 else f"duplicate images within a split: {files}")
    report["class_counts"] = dict(class_counts)
    total = sum(class_counts.values())
    if total:
        mx, mn = max(class_counts.values()), min(class_counts.values()) if len(class_counts) == len(class_names) else 0
        if mn == 0 or mx / mn > 3:
            report["warnings"].append("class imbalance: largest/smallest instance ratio > 3 (or a class has no instances)")
    report["ok"] = not report["errors"] and not report["leakage"]
    return report


def _read_names(yaml_path: Path) -> list[str] | None:
    """Tiny parser for the `names:` section (list or index map) so PyYAML is not required."""
    lines = yaml_path.read_text().splitlines()
    names: dict[int, str] = {}
    in_names = False
    for line in lines:
        if line.strip().startswith("names:"):
            rest = line.split(":", 1)[1].strip()
            if rest.startswith("["):
                return [x.strip().strip("'\"") for x in rest.strip("[]").split(",") if x.strip()]
            in_names = True
            continue
        if in_names:
            if not line.startswith((" ", "\t", "-")) and line.strip():
                break
            s = line.strip()
            if s.startswith("-"):
                names[len(names)] = s[1:].strip().strip("'\"")
            elif ":" in s:
                k, v = s.split(":", 1)
                names[int(k)] = v.strip().strip("'\"")
    return [names[i] for i in sorted(names)] or None


def write_data_yaml(root: Path, class_names: list[str]) -> Path:
    p = Path(root) / "data.yaml"
    body = [f"path: {Path(root).resolve()}", "train: images/train", "val: images/val", "test: images/test", "names:"]
    body += [f"  {i}: {n}" for i, n in enumerate(class_names)]
    p.write_text("\n".join(body) + "\n")
    return p


def split_dataset(images: Path, labels: Path, out: Path, class_names: list[str], ratios=(0.7, 0.2, 0.1), seed: int = 42) -> dict:
    """Split a flat images/labels folder into train/val/test without leakage.

    Identical images (same SHA-256) are grouped and always land in the same split. Groups are
    stratified by their rarest class so every split sees every class where possible.
    """
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError("ratios must sum to 1")
    images, labels, out = Path(images), Path(labels), Path(out)
    groups: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(images.iterdir()):
        if p.suffix.lower() in IMG_EXT:
            groups[sha256_file(p)].append(p)
    def rarest_class(group: list[Path]) -> int:
        lbl = labels / (group[0].stem + ".txt")
        cls = [r[0] for r in read_label_file(lbl, len(class_names))[0]] if lbl.is_file() else []
        return min(cls) if cls else -1
    strata: dict[int, list[list[Path]]] = defaultdict(list)
    for g in groups.values():
        strata[rarest_class(g)].append(g)
    rng = random.Random(seed)
    assign: dict[str, list[Path]] = {s: [] for s in SPLITS}
    for key in sorted(strata):
        gl = strata[key]
        rng.shuffle(gl)
        n = len(gl)
        n_train = round(n * ratios[0]); n_val = round(n * ratios[1])
        if n >= 3:
            n_val = max(n_val, 1)
            n_test = n - n_train - n_val
            if n_test < 1 and ratios[2] > 0:
                n_train -= 1
        parts = {"train": gl[:n_train], "val": gl[n_train : n_train + n_val], "test": gl[n_train + n_val :]}
        for s, items in parts.items():
            for g in items:
                assign[s] += g
    for s in SPLITS:
        (out / "images" / s).mkdir(parents=True, exist_ok=True)
        (out / "labels" / s).mkdir(parents=True, exist_ok=True)
        for img in assign[s]:
            shutil.copy2(img, out / "images" / s / img.name)
            lbl = labels / (img.stem + ".txt")
            if lbl.is_file():
                shutil.copy2(lbl, out / "labels" / s / lbl.name)
    write_data_yaml(out, class_names)
    manifest = {"seed": seed, "ratios": list(ratios), "counts": {s: len(v) for s, v in assign.items()},
                "files": {s: sorted(p.name for p in v) for s, v in assign.items()}}
    (out / "SPLIT_MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def voc_to_yolo(images: Path, annotations: Path, out: Path, class_names: list[str]) -> dict:
    """Convert Pascal-VOC XML (as shipped with NEU-DET) into flat YOLO images/ + labels/ folders."""
    images, annotations, out = Path(images), Path(annotations), Path(out)
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    converted = skipped = 0
    index = {c.lower(): i for i, c in enumerate(class_names)}
    by_stem: dict[str, Path] = {p.stem: p for p in images.rglob("*") if p.suffix.lower() in IMG_EXT}
    for xml in sorted(annotations.rglob("*.xml")):
        root = ET.parse(xml).getroot()
        fname = root.findtext("filename") or xml.stem
        stem = Path(fname).stem
        img = by_stem.get(stem) or by_stem.get(xml.stem)
        size = root.find("size")
        if img is None or size is None:
            skipped += 1
            continue
        w, h = float(size.findtext("width")), float(size.findtext("height"))
        lines = []
        for obj in root.findall("object"):
            name = (obj.findtext("name") or "").strip().lower()
            if name not in index:
                raise ValueError(f"{xml.name}: unknown class {name!r}; pass the full class list with --classes")
            bb = obj.find("bndbox")
            x1, y1, x2, y2 = (float(bb.findtext(k)) for k in ("xmin", "ymin", "xmax", "ymax"))
            lines.append(f"{index[name]} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
        shutil.copy2(img, out / "images" / img.name)
        (out / "labels" / (img.stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
        converted += 1
    return {"converted": converted, "skipped_no_image_or_size": skipped}


def make_synthetic_dataset(out: Path, count: int = 240, seed: int = 0, size: int = 640, clean_fraction: float = 0.2) -> dict:
    """SYNTHETIC demonstration dataset. Every image is unique, so splits cannot leak."""
    out = Path(out)
    rng = random.Random(seed)
    splits = (["train"] * 70 + ["val"] * 20 + ["test"] * 10)
    for i in range(count):
        split = rng.choice(splits) if i >= 10 else SPLITS[i % 3]  # first images guarantee every split exists
        (out / "images" / split).mkdir(parents=True, exist_ok=True)
        (out / "labels" / split).mkdir(parents=True, exist_ok=True)
        defective = rng.random() > clean_fraction
        img, labels = synthetic.make_sample(seed * 100_000 + i, defective, (size, size))
        name = f"syn_{i:05d}"
        cv2.imwrite(str(out / "images" / split / f"{name}.png"), img)
        lines = [f"{c} {(x1 + x2) / 2 / size:.6f} {(y1 + y2) / 2 / size:.6f} {(x2 - x1) / size:.6f} {(y2 - y1) / size:.6f}" for c, (x1, y1, x2, y2) in labels]
        (out / "labels" / split / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    write_data_yaml(out, synthetic.SYNTHETIC_CLASSES)
    (out / SYNTHETIC_MARKER).write_text("Synthetic demonstration data generated by backend/ml/dataset_tools.py.\nNot real defect data; "
                                        "metrics computed on it do not represent real-world performance.\n")
    (out / "README.md").write_text("# Synthetic demo dataset\n\nGenerated procedurally (rendered scratches and pits on a synthetic metal texture). "
                                   "Licence: generated by this project (MIT). **Do not report results on this dataset as real defect detection performance.**\n")
    return {"count": count, "classes": synthetic.SYNTHETIC_CLASSES}


def main(argv=None) -> int:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("--root", required=True); v.add_argument("--classes", nargs="*")
    s = sub.add_parser("split"); s.add_argument("--images", required=True); s.add_argument("--labels", required=True)
    s.add_argument("--out", required=True); s.add_argument("--classes", nargs="+", required=True); s.add_argument("--seed", type=int, default=42)
    c = sub.add_parser("voc2yolo"); c.add_argument("--images", required=True); c.add_argument("--annotations", required=True)
    c.add_argument("--out", required=True); c.add_argument("--classes", nargs="+", required=True)
    g = sub.add_parser("synthetic"); g.add_argument("--out", required=True); g.add_argument("--count", type=int, default=240); g.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    if a.cmd == "validate":
        rep = validate_yolo_dataset(Path(a.root), a.classes)
        print(json.dumps(rep, indent=1))
        return 0 if rep["ok"] else 1
    if a.cmd == "split":
        print(json.dumps(split_dataset(Path(a.images), Path(a.labels), Path(a.out), a.classes, seed=a.seed)["counts"]))
    elif a.cmd == "voc2yolo":
        print(json.dumps(voc_to_yolo(Path(a.images), Path(a.annotations), Path(a.out), a.classes)))
    else:
        print(json.dumps(make_synthetic_dataset(Path(a.out), a.count, a.seed)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
