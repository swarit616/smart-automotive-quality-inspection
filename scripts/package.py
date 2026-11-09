#!/usr/bin/env python3
"""Create ../smart-automotive-quality-inspection.zip without caches, venvs, node_modules or secrets."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT.parent / f"{ROOT.name}.zip"
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", ".git", "runs", "outputs", "demo_output"}
SKIP_FILES = {".env"}
SKIP_SUFFIX = {".pyc", ".db", ".pt", ".onnx"}

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if p.is_dir() or SKIP_DIRS & set(rel.parts) or p.name in SKIP_FILES or p.suffix in SKIP_SUFFIX:
            continue
        if rel.parts[0] == "data" and p.name != ".gitkeep":
            continue
        z.write(p, Path(ROOT.name) / rel)
print(OUT)
