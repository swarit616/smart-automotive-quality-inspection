import unittest

import numpy as np

from app.core.boxes import BBox, BoxError, class_aware_nms, iou, nms, validate_box, validate_yolo_box, yolo_to_xyxy
from app.core.preprocessing import (ImageValidationError, letterbox, sniff_format, to_model_input, undo_letterbox,
                                    validate_and_decode)
from tests.helpers import jpg_bytes, png_bytes

LIM = dict(max_bytes=1_000_000, max_pixels=1_000_000, min_side=32)


class BoxTests(unittest.TestCase):
    def test_iou_identical_disjoint_partial(self):
        a = BBox(0, 0, 10, 10)
        self.assertAlmostEqual(iou(a, a), 1.0)
        self.assertEqual(iou(a, BBox(20, 20, 30, 30)), 0.0)
        self.assertAlmostEqual(iou(a, BBox(5, 0, 15, 10)), 50 / 150)

    def test_validate_box_rejects_bad_boxes(self):
        for bad in (BBox(5, 5, 5, 10), BBox(10, 0, 5, 5), BBox(float("nan"), 0, 5, 5), BBox(-1, 0, 5, 5), BBox(0, 0, 200, 5)):
            with self.assertRaises(BoxError):
                validate_box(bad, 100, 100)

    def test_validate_box_clip(self):
        b = validate_box(BBox(-5, -5, 50, 200), 100, 100, clip=True)
        self.assertEqual((b.x1, b.y1, b.x2, b.y2), (0, 0, 50, 100))
        with self.assertRaises(BoxError):
            validate_box(BBox(150, 150, 200, 200), 100, 100, clip=True)

    def test_validate_yolo_box(self):
        validate_yolo_box(0.5, 0.5, 0.2, 0.2)
        for bad in ((1.2, 0.5, 0.2, 0.2), (0.5, 0.5, 0.0, 0.2), (0.05, 0.5, 0.3, 0.2), (float("nan"), 0.5, 0.2, 0.2)):
            with self.assertRaises(BoxError):
                validate_yolo_box(*bad)

    def test_yolo_to_xyxy(self):
        b = yolo_to_xyxy(0.5, 0.5, 0.5, 0.25, 200, 100)
        self.assertEqual((b.x1, b.y1, b.x2, b.y2), (50, 37.5, 150, 62.5))

    def test_nms_suppresses_overlap_keeps_best(self):
        boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], float)
        keep = nms(boxes, np.array([0.6, 0.9, 0.5]), 0.5)
        self.assertEqual(keep, [1, 2])

    def test_nms_empty_and_class_aware(self):
        self.assertEqual(nms(np.zeros((0, 4)), np.zeros(0), 0.5), [])
        boxes = np.array([[0, 0, 10, 10], [0, 0, 10, 10]], float)
        self.assertEqual(sorted(class_aware_nms(boxes, np.array([0.9, 0.8]), [0, 1], 0.5)), [0, 1])
        self.assertEqual(len(class_aware_nms(boxes, np.array([0.9, 0.8]), [0, 0], 0.5)), 1)


class PreprocessingTests(unittest.TestCase):
    def test_accepts_png_and_jpeg(self):
        self.assertEqual(validate_and_decode(png_bytes(), **LIM).fmt, "png")
        v = validate_and_decode(jpg_bytes(), **LIM)
        self.assertEqual((v.fmt, v.width, v.height, v.extension), ("jpeg", 128, 96, ".jpg"))

    def test_rejects_bad_inputs(self):
        for data in (b"", b"GIF89a....", b"not an image at all", png_bytes()[:40]):
            with self.assertRaises(ImageValidationError):
                validate_and_decode(data, **LIM)

    def test_rejects_oversized_file_and_dimensions_and_tiny(self):
        with self.assertRaises(ImageValidationError):
            validate_and_decode(png_bytes(), max_bytes=10, max_pixels=10**6, min_side=1)
        with self.assertRaises(ImageValidationError):
            validate_and_decode(png_bytes(2000, 2000), max_bytes=10**8, max_pixels=1_000_000, min_side=1)
        with self.assertRaises(ImageValidationError):
            validate_and_decode(png_bytes(16, 16), **LIM)

    def test_sniff_ignores_extension(self):
        self.assertIsNone(sniff_format(b"<html>"))

    def test_letterbox_roundtrip(self):
        img = np.zeros((100, 200, 3), np.uint8)
        lb = letterbox(img, 640)
        self.assertEqual(lb.image.shape, (640, 640, 3))
        box = np.array([[100.0, 50.0, 140.0, 90.0]])
        mapped = box * lb.scale + np.array([lb.pad_x, lb.pad_y, lb.pad_x, lb.pad_y])
        back = undo_letterbox(mapped, lb, 200, 100)
        np.testing.assert_allclose(back, box, atol=1.0)

    def test_model_input_layout(self):
        t, _ = to_model_input(np.zeros((50, 80, 3), np.uint8), 320)
        self.assertEqual(t.shape, (1, 3, 320, 320))
        self.assertEqual(t.dtype, np.float32)
        self.assertLessEqual(float(t.max()), 1.0)


if __name__ == "__main__":
    unittest.main()
