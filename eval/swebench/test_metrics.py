from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.swebench.metrics import (  # noqa: E402
    files_from_patch,
    fingerprint_ids,
    load_instance_ids,
    localization_hit_rate,
    summarize_predictions,
)


def test_files_from_patch_and_hit_rate() -> None:
    gold = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-x
+y
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1 +1 @@
-u
+v
"""
    model = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-x
+y
"""
    assert files_from_patch(gold) == {"a.py", "b.py"}
    assert localization_hit_rate(model_patch=model, gold_patch=gold) == 0.5


def test_summarize_predictions_empty_diff() -> None:
    summary = summarize_predictions(
        [{"instance_id": "x", "model_patch": ""}],
        {"x": "+++ b/a.py\n"},
    )
    assert summary["empty_diff_count"] == 1


def test_lite50_fingerprint_stable() -> None:
    path = Path(__file__).with_name("lite50.txt")
    ids = load_instance_ids(path)
    assert len(ids) == 50
    assert fingerprint_ids(ids) == fingerprint_ids(list(ids))
