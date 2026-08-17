from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app.services.ops.l1.retry_ids import (  # noqa: E402
    MAX_RETRY_CASE_IDS,
    context_case_matches,
    retrieval_query_matches,
    split_retry_case_ids,
)


def test_max_retry_case_ids_covers_lite_full() -> None:
    assert MAX_RETRY_CASE_IDS >= 300


def test_split_retry_case_ids() -> None:
    parts = split_retry_case_ids(
        [
            "astropy__astropy-14365",
            "beir.scifact.q-1",
            "cmteb.tnews.q-9",
            "longbench.qasper.3",
            "astropy__astropy-14365",
            "",
        ]
    )
    assert parts["coding"] == ["astropy__astropy-14365"]
    assert parts["retrieval"] == ["beir.scifact.q-1"]
    assert parts["retrieval_zh"] == ["cmteb.tnews.q-9"]
    assert parts["context"] == ["longbench.qasper.3"]


def test_retrieval_query_matches() -> None:
    wanted = {"beir.scifact.q-12"}
    assert retrieval_query_matches(
        "scifact", "12", prefix="beir", wanted=wanted
    )
    assert not retrieval_query_matches(
        "fiqa", "12", prefix="beir", wanted=wanted
    )


def test_context_case_matches() -> None:
    wanted = {"longbench.qasper.3"}
    assert context_case_matches("qasper", 3, wanted)
    assert not context_case_matches("qasper", 2, wanted)
