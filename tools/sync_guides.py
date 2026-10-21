"""Copy the docs that `kankuro guide` prints into the package (kankuro/guides/).

    python tools/sync_guides.py

docs/ is the source of truth; tests/test_guides.py fails when the copies drift.
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from kankuro.cli import GUIDES  # noqa: E402

dst = os.path.join(ROOT, "kankuro", "guides")
os.makedirs(dst, exist_ok=True)
for fn, _ in GUIDES.values():
    shutil.copyfile(os.path.join(ROOT, "docs", fn), os.path.join(dst, fn))
    print("synced", fn)
