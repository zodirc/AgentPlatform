from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.pull import (  # noqa: E402
    _longbench_jsonl_path,
    _normalize_longbench_row,
    _pull_longbench_from_zip,
    _read_longbench_task_jsonl,
)


def test_normalize_longbench_row_maps_fields() -> None:
    row = _normalize_longbench_row(
        "hotpotqa",
        0,
        {
            "input": "Q?",
            "context": "CTX",
            "answers": ["A"],
            "length": 12,
            "dataset": "hotpotqa",
            "language": "en",
        },
    )
    assert row["task"] == "hotpotqa"
    assert row["question"] == "Q?"
    assert row["context"] == "CTX"
    assert row["answers"] == ["A"]


def test_read_longbench_task_jsonl_respects_max_n(tmp_path: Path) -> None:
    p = tmp_path / "multifieldqa_en.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for i in range(5):
            f.write(json.dumps({"input": f"q{i}", "context": f"c{i}", "answers": [f"a{i}"]}) + "\n")
    rows = _read_longbench_task_jsonl(p, task="multifieldqa_en", max_n=3)
    assert len(rows) == 3
    assert rows[2]["idx"] == 2
    assert rows[2]["input"] == "q2"


def test_pull_longbench_from_local_zip(tmp_path: Path, monkeypatch) -> None:
    """Zip path must work without HuggingFace `datasets` / remote scripts."""
    raw_zip = tmp_path / "src.zip"
    with zipfile.ZipFile(raw_zip, "w") as zf:
        for task in ("multifieldqa_en", "hotpotqa", "narrativeqa"):
            payload = "\n".join(
                json.dumps(
                    {
                        "input": f"{task}-q{i}",
                        "context": f"{task}-ctx{i}",
                        "answers": [f"{task}-a{i}"],
                        "length": 10,
                        "dataset": task,
                        "language": "en",
                    }
                )
                for i in range(2)
            )
            zf.writestr(f"data/{task}.jsonl", payload + "\n")

    root = tmp_path / "longbench"
    root.mkdir()
    # Pretend download already produced data.zip
    dest_zip = root / "data.zip"
    dest_zip.write_bytes(raw_zip.read_bytes())

    def _no_download(*_a, **_k):  # pragma: no cover - must not be called
        raise AssertionError("should use cached zip")

    monkeypatch.setattr("official_bench.pull._download", _no_download)

    ctx = {
        "tasks": ["multifieldqa_en", "hotpotqa", "narrativeqa"],
        "max_samples_per_task": 1,
        "hf_data_zip": "https://example.invalid/data.zip",
    }
    rows = _pull_longbench_from_zip(root, ctx, force=False)
    assert len(rows) == 3
    assert {r["task"] for r in rows} == {"multifieldqa_en", "hotpotqa", "narrativeqa"}
    assert all(r["idx"] == 0 for r in rows)

    path = _longbench_jsonl_path(root / "raw", "hotpotqa")
    assert path is not None and path.is_file()
