import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.core.detectors import DemoDetector
from ml.dataset_tools import (SPLITS, make_synthetic_dataset, read_label_file, sha256_file, split_dataset,
                              validate_yolo_dataset, voc_to_yolo, write_data_yaml)
from ml.evaluate import run_evaluation


class DatasetToolsTests(unittest.TestCase):
    def test_synthetic_dataset_is_valid_and_leak_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_synthetic_dataset(Path(tmp), count=40, seed=1, size=320)
            rep = validate_yolo_dataset(Path(tmp))
            self.assertTrue(rep["ok"], rep["errors"] + rep["leakage"])
            self.assertEqual(set(rep["splits"]), set(SPLITS))
            self.assertEqual(sum(s["images"] for s in rep["splits"].values()), 40)
            self.assertTrue((Path(tmp) / "SYNTHETIC_DATASET").is_file())

    def test_validation_catches_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for s in ("train", "val"):
                (root / "images" / s).mkdir(parents=True); (root / "labels" / s).mkdir(parents=True)
            img = np.full((64, 64, 3), 100, np.uint8)
            cv2.imwrite(str(root / "images/train/a.png"), img)
            cv2.imwrite(str(root / "images/val/a_copy.png"), img)            # identical content in two splits -> leakage
            (root / "images/train/broken.png").write_bytes(b"not a png")      # unreadable
            (root / "labels/train/a.txt").write_text("5 0.5 0.5 0.2 0.2\n0 1.5 0.5 0.2 0.2\n0 0.5 0.5\n")
            (root / "labels/train/orphan.txt").write_text("0 0.5 0.5 0.2 0.2\n")
            rep = validate_yolo_dataset(root, ["scratch", "pit"])
            text = "\n".join(rep["errors"])
            for needle in ("unreadable image", "class id 5", "outside [0, 1]", "expected 5 values", "label without image"):
                self.assertIn(needle, text)
            self.assertEqual(len(rep["leakage"]), 1)
            self.assertFalse(rep["ok"])

    def test_split_has_no_leakage_even_with_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw"; (raw / "images").mkdir(parents=True); (raw / "labels").mkdir()
            rng = np.random.default_rng(0)
            for i in range(30):
                img = rng.integers(0, 255, (48, 48, 3), dtype=np.uint8)
                for suffix in ("", "_dup") if i < 6 else ("",):
                    cv2.imwrite(str(raw / "images" / f"i{i}{suffix}.png"), img)
                    (raw / "labels" / f"i{i}{suffix}.txt").write_text(f"{i % 3} 0.5 0.5 0.3 0.3\n")
            out = Path(tmp) / "out"
            m = split_dataset(raw / "images", raw / "labels", out, ["a", "b", "c"], seed=3)
            self.assertEqual(sum(m["counts"].values()), 36)
            self.assertTrue(all(m["counts"][s] > 0 for s in SPLITS))
            seen = {}
            for s in SPLITS:
                for p in (out / "images" / s).iterdir():
                    h = sha256_file(p)
                    self.assertNotIn(seen.get(h), [x for x in SPLITS if x != s], "identical image in two splits")
                    seen[h] = s
            self.assertTrue(validate_yolo_dataset(out)["ok"])
            self.assertEqual(split_dataset(raw / "images", raw / "labels", Path(tmp) / "out2", ["a", "b", "c"], seed=3)["files"], m["files"])  # deterministic

    def test_voc_conversion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "im").mkdir(); (root / "xml").mkdir()
            cv2.imwrite(str(root / "im/crazing_1.jpg"), np.zeros((200, 200, 3), np.uint8))
            (root / "xml/crazing_1.xml").write_text(
                "<annotation><filename>crazing_1.jpg</filename><size><width>200</width><height>200</height></size>"
                "<object><name>crazing</name><bndbox><xmin>20</xmin><ymin>40</ymin><xmax>120</xmax><ymax>100</ymax></bndbox></object></annotation>")
            r = voc_to_yolo(root / "im", root / "xml", root / "out", ["crazing", "scratches"])
            self.assertEqual(r["converted"], 1)
            rows, errs = read_label_file(root / "out/labels/crazing_1.txt", 2)
            self.assertEqual(errs, [])
            self.assertEqual([round(v, 3) for v in rows[0][1:]], [0.35, 0.35, 0.5, 0.3])

    def test_data_yaml_names_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_data_yaml(Path(tmp), ["x", "y z"])
            from ml.dataset_tools import _read_names
            self.assertEqual(_read_names(Path(tmp) / "data.yaml"), ["x", "y z"])


class EvaluationPipelineTests(unittest.TestCase):
    def test_run_evaluation_structure_on_synthetic_split(self):
        """Pipeline check only: the demo heuristic is evaluated on SYNTHETIC data; values are not a real metric."""
        with tempfile.TemporaryDirectory() as tmp:
            make_synthetic_dataset(Path(tmp), count=30, seed=2, size=320)
            res = run_evaluation(DemoDetector(), Path(tmp), "test", 0.25)
            for k in ("precision", "recall", "f1", "map50", "map50_95", "per_class", "confusion_matrix", "n_images"):
                self.assertIn(k, res)
            self.assertTrue(res["synthetic_dataset"])
            self.assertGreater(res["n_images"], 0)

    def test_requires_heldout_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_synthetic_dataset(Path(tmp), count=12, seed=2, size=320)
            with self.assertRaises(ValueError):
                run_evaluation(DemoDetector(), Path(tmp), "nonexistent_split")


if __name__ == "__main__":
    unittest.main()
