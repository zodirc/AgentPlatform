"""Unit tests for CTX-13 fold evidence-loss audit helpers (no Docker)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.ctx13_fold_evidence_audit import (  # noqa: E402
    CaseAudit,
    EvidenceSpan,
    classify_case,
    evidence_in_text,
    gold_cover_ratio,
    has_folded_stub,
    has_reread_pointer,
    locate_evidence_span,
    simulate_budget_head,
    summarize,
    tool_payload_body,
)


def test_locate_evidence_exact() -> None:
    passage = "Prelude. The answer is Flexibility. Epilogue about other topics."
    span = locate_evidence_span(passage, ["Flexibility."])
    assert span is not None
    assert "Flexibility" in span.text


def test_locate_evidence_dense_cover() -> None:
    passage = (
        "The team won their first game of the season with a final score of 15–3 "
        "against the visitors in Columbus."
    )
    gold = "They won their first game with a score of 15-3."
    span = locate_evidence_span(passage, [gold])
    assert span is not None
    assert span.score >= 0.45
    assert "15" in span.text


def test_simulate_budget_drops_tail_evidence() -> None:
    body = "HEAD " + ("x" * 4000) + " TAIL_EVIDENCE_MARKER"
    wrapped = '{"path":"sources/passage.md","content":"' + body + '"}'
    kept = simulate_budget_head(wrapped, 4000)
    assert "budget_truncated" in kept
    assert "TAIL_EVIDENCE_MARKER" not in kept


def test_tool_payload_body_and_folded() -> None:
    raw = '{"path":"sources/passage.md","content":"hello world","_folded_read":true}'
    assert tool_payload_body(raw) == "hello world"
    assert has_folded_stub(raw)


def test_has_reread_pointer_from_stub() -> None:
    texts = [
        '{"path":"sources/passage.md","offset":1,"next_offset":101,'
        '"content":"[omitted; already read this Turn]","_folded_read":true}'
    ]
    assert has_reread_pointer(texts)


def test_evidence_in_text_cover() -> None:
    span = EvidenceSpan(0, 20, 0.9, "dense", "Flexibility", "Flexibility matters")
    assert evidence_in_text(span, ["Flexibility."], "note: Flexibility matters here")
    assert gold_cover_ratio("Flexibility.", "Flexibility matters") >= 0.55


def test_classify_trunc_window_miss() -> None:
    # Evidence only in late lines; latest read covers full passage but 32k budget
    # simulation will not trigger on short text — craft long passage.
    head = "A" * 30_000
    evidence = "SecretTokenXYZ is the key answer here."
    passage = head + "\n" + evidence + "\n"
    golds = ["SecretTokenXYZ"]
    # One read covering whole file
    windows = [{"path": "sources/passage.md", "offset": 1, "end_line": 3, "chars_read": len(passage)}]
    # Final envelope: truncated head only
    trunc = simulate_budget_head(
        '{"path":"sources/passage.md","content":"' + passage[:100].replace('"', "") + '"}',
        100,
    )
    # Build a realistic truncated tool body without evidence
    tool_text = (
        '{"path":"sources/passage.md","content":"'
        + ("A" * 500)
        + '"}\n...[budget_truncated]'
    )
    envelopes = [
        (
            0,
            [
                {
                    "role": "tool",
                    "content": [{"type": "tool_result", "content": tool_text}],
                }
            ],
        )
    ]
    case = {
        "case_id": "longbench.demo.0",
        "turn_id": "00000000-0000-0000-0000-000000000001",
        "bucket": "wrong_answer_after_read",
        "n_reads": 1,
        "read_coverage": 0.9,
        "used_next_offset": False,
    }
    audit = classify_case(
        run_id="demo",
        case=case,
        golds=golds,
        passage=passage,
        envelopes=envelopes,
        read_windows=windows,
    )
    assert audit.primary == "trunc_window_miss", audit


def test_classify_not_assembly_when_visible() -> None:
    passage = "Intro. The capital is Paris. Outro."
    golds = ["Paris"]
    tool_text = '{"path":"sources/passage.md","content":"Intro. The capital is Paris. Outro."}'
    envelopes = [
        (
            0,
            [
                {
                    "role": "tool",
                    "content": [{"type": "tool_result", "content": tool_text}],
                }
            ],
        )
    ]
    windows = [{"path": "sources/passage.md", "offset": 1, "end_line": 1, "chars_read": len(passage)}]
    audit = classify_case(
        run_id="demo",
        case={
            "case_id": "longbench.demo.1",
            "turn_id": "t",
            "bucket": "wrong_answer_after_read",
            "n_reads": 1,
            "read_coverage": 1.0,
            "used_next_offset": False,
        },
        golds=golds,
        passage=passage,
        envelopes=envelopes,
        read_windows=windows,
    )
    assert audit.primary == "not_assembly_loss"


def test_summarize_verdict_first_knife() -> None:
    audits = [
        CaseAudit("r", "c1", "wrong_answer_after_read", "t1", "trunc_window_miss"),
        CaseAudit("r", "c2", "wrong_answer_after_read", "t2", "trunc_window_miss"),
        CaseAudit("r", "c3", "wrong_answer_after_read", "t3", "trunc_window_miss"),
        CaseAudit("r", "c4", "wrong_answer_after_read", "t4", "not_assembly_loss"),
        CaseAudit("r", "c5", "wrong_answer_after_read", "t5", "pointer_lost"),
        CaseAudit("r", "c6", "truly_abandoned", "t6", "never_retrieved"),
    ]
    s = summarize(audits)
    assert s["trunc_window_miss"] == 3
    assert s["first_knife"] == "CTX-14"
    assert "CTX-14" in s["verdict_line"]
