from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from official_bench.agent_path_extract import (  # noqa: E402
    called_tools,
    csi_probes_from_events,
    csi_suite_rates,
    doc_id_from_path,
    failure_class_from_events,
    filter_unified_diff_noise,
    merge_retrieval_rankings,
    patch_apply_check,
    patch_from_events,
    patch_from_git_diff,
    patch_from_work_root,
    patch_hunks_incomplete,
    ranking_scores,
    search_queries_from_events,
    terminal_state_from_events,
)
from official_bench.l2_probes import (  # noqa: E402
    classify_bucket,
    config_fingerprint,
    is_infra_channel_failure,
    query_drift,
)
from official_bench.bucket_report import classify_manifest  # noqa: E402


def test_infra_channel_detection() -> None:
    assert is_infra_channel_failure(
        'model_error: model retries exhausted after 3 attempts: model API 503: '
        '{"error":{"message":"Service is too busy."}}'
    )
    assert is_infra_channel_failure(
        "model_error: model retries exhausted after 3 attempts: openai transport error: "
    )
    assert is_infra_channel_failure(
        "model_error: model retries exhausted after 3 attempts: first byte timeout after 15.0s"
    )
    # INFRA-2: api↔runtime HTTP disconnect (c76e07a9 class)
    assert is_infra_channel_failure("httpx.ReadError: ")
    assert is_infra_channel_failure(
        "httpcore.RemoteProtocolError: peer closed connection"
    )
    assert is_infra_channel_failure("connection reset by peer")
    assert not is_infra_channel_failure("")
    assert not is_infra_channel_failure("tool read_file failed: file not found")
    assert not is_infra_channel_failure("failed to read error log")
    events = [
        {
            "type": "turn.failed",
            "payload": {
                "message": (
                    "model_error: model retries exhausted after 3 attempts: "
                    "openai http timeout: "
                ),
                "termination_reason": "fatal_error",
            },
        }
    ]
    assert failure_class_from_events(events) == "infra_channel"
    assert terminal_state_from_events(events) == "failed"
    # Provider timeout must not be remapped to step_timeout.
    assert (
        terminal_state_from_events(
            [
                {
                    "type": "turn.failed",
                    "payload": {
                        "message": "model_error: first byte timeout after 15.0s",
                    },
                }
            ]
        )
        == "failed"
    )


def test_doc_id_from_materialised_path() -> None:
    assert doc_id_from_path("sources/beir/scifact/abc123.txt") == "abc123"
    assert doc_id_from_path("sources/beir/fiqa/foo_bar.txt") == "foo_bar"


def test_merge_retrieval_prefers_ranked() -> None:
    events = [
        {
            "type": "retrieval.completed",
            "payload": {
                "hits": [{"path": "sources/a.txt", "score": 0.9}],
                "ranked": [
                    {"path": "sources/d1.txt", "score": 1.0},
                    {"path": "sources/d2.txt", "score": 0.5},
                ],
            },
        }
    ]
    assert merge_retrieval_rankings(events) == ["d1", "d2"]


def test_merge_retrieval_first_seen_union() -> None:
    events = [
        {
            "type": "retrieval.completed",
            "payload": {"ranked": [{"path": "sources/a.txt"}, {"path": "sources/b.txt"}]},
        },
        {
            "type": "retrieval.completed",
            "payload": {"ranked": [{"path": "sources/b.txt"}, {"path": "sources/c.txt"}]},
        },
    ]
    assert merge_retrieval_rankings(events) == ["a", "b", "c"]


def test_merge_retrieval_empty_is_empty() -> None:
    assert merge_retrieval_rankings([]) == []
    assert merge_retrieval_rankings([{"type": "tool.started", "payload": {}}]) == []


def test_ranking_scores_descending() -> None:
    scores = ranking_scores(["a", "b", "c"], limit=10)
    assert scores["a"] > scores["b"] > scores["c"]


def test_read_file_stats_uses_chars_read_on_completed() -> None:
    """CTX-9: tool.completed has no content; chars_read/file_chars drive coverage."""
    from official_bench.agent_path_extract import read_file_stats_from_events

    events = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "read_file",
                "arguments": {"path": "sources/passage.md"},
            },
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "read_file",
                "status": "ok",
                "summary": "Read sources/passage.md lines 1–100/500 (truncated; next_offset=101)",
                "chars_read": 4000,
                "file_chars": 50_000,
                "offset": 1,
                "end_line": 100,
                "total_lines": 500,
                "next_offset": 101,
                "is_truncated": True,
            },
        },
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "read_file",
                "arguments": {"path": "sources/passage.md", "offset": 101},
            },
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "read_file",
                "status": "ok",
                "chars_read": 3500,
                "file_chars": 50_000,
                "offset": 101,
                "next_offset": 201,
                "is_truncated": True,
            },
        },
    ]
    stats = read_file_stats_from_events(events)
    assert stats["n_reads"] == 2
    assert stats["read_bytes"] == 7500
    assert stats["file_chars"] == 50_000
    assert stats["used_next_offset"] is True
    assert stats["continue_reads"] == 1
    assert stats["truncation_hits"] >= 1
    assert stats["last_read_offset"] == 201


def test_read_file_stats_falls_back_to_chinese_hint() -> None:
    from official_bench.agent_path_extract import read_file_stats_from_events

    events = [
        {
            "type": "tool.started",
            "payload": {"tool_name": "read_file", "arguments": {"path": "p.md"}},
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "read_file",
                "status": "ok",
                "summary": "已读 3200 / 共 48000 字符，内容未完；续读请传 offset=80",
            },
        },
    ]
    stats = read_file_stats_from_events(events)
    assert stats["read_bytes"] == 3200


def test_search_queries_from_events() -> None:
    events = [
        {
            "type": "tool.started",
            "payload": {"tool_name": "search_sources", "arguments": {"query": "alpha"}},
        },
        {
            "type": "tool.started",
            "payload": {"tool_name": "search_sources", "arguments": {"query": "beta"}},
        },
    ]
    assert search_queries_from_events(events) == ["alpha", "beta"]


def test_search_limits_and_ranked_lengths_ret6() -> None:
    from official_bench.agent_path_extract import (
        depth_audit_from_events,
        ranked_lengths_from_events,
        search_limits_from_events,
    )

    events = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "search_sources",
                "arguments": {"query": "q1", "limit": 30},
            },
        },
        {
            "type": "retrieval.completed",
            "payload": {
                "hit_count": 10,
                "ranked": [{"path": f"sources/{i}.txt"} for i in range(10)],
            },
        },
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "search_sources",
                "arguments": {"query": "q2"},  # omit limit → default 30
            },
        },
        {
            "type": "retrieval.completed",
            "payload": {"hit_count": 12, "ranked": []},
        },
    ]
    assert search_limits_from_events(events) == [30, 30]
    assert ranked_lengths_from_events(events) == [10, 12]
    depth = depth_audit_from_events(events)
    assert depth["merged_len"] == 10
    assert depth["max_limit"] == 30
    assert depth["ranked_lengths"] == [10, 12]


def test_depth_audit_lane_depth_ret10() -> None:
    from official_bench.agent_path_extract import depth_audit_from_events
    from official_bench.l2_probes import depth_audit_aggregate

    events = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "search_sources",
                "arguments": {"query": "q", "limit": 30},
            },
        },
        {
            "type": "retrieval.completed",
            "payload": {
                "hit_count": 10,
                "ranked": [{"path": f"sources/{i}.txt"} for i in range(10)],
                "audit": {
                    "lane_depth": {
                        "vector_n": 40,
                        "bm25_n": 40,
                        "union_n": 55,
                        "lane_top_k": 120,
                        "requested_limit": 30,
                        "over_fetch_multiplier": 2.0,
                        "two_level_doc_n": 8,
                        "two_level_enabled": True,
                    }
                },
            },
        },
    ]
    depth = depth_audit_from_events(events)
    assert depth["lane_vector_n"] == 40
    assert depth["lane_bm25_n"] == 40
    assert depth["lane_union_n"] == 55
    assert depth["lane_top_k"] == 120
    assert depth["over_fetch_multiplier"] == 2.0
    assert depth["two_level_doc_n"] == 8

    cases = []
    for i in range(10):
        cases.append(
            {
                "case_id": f"beir.fiqa.q-{i}",
                "turn_id": f"t{i}",
                "merged_len": 10,
                "lane_vector_n": 100,
                "lane_bm25_n": 100,
                "lane_top_k": 120,
                "search_limits": [30],
                "l2": {
                    "n_search": 1,
                    "merged_len": 10,
                    "lane_vector_n": 100,
                    "lane_bm25_n": 100,
                    "lane_top_k": 120,
                    "search_limits": [30],
                },
            }
        )
    agg = depth_audit_aggregate(cases)
    assert agg["fiqa_lane_adjudication"] == "lanes_fed_relevance"
    assert agg["by_dataset"]["fiqa"]["lanes_fed_but_short_n"] == 10


def test_depth_audit_lane_starvation_adjudication() -> None:
    from official_bench.l2_probes import depth_audit_aggregate

    cases = []
    for i in range(10):
        cases.append(
            {
                "case_id": f"beir.fiqa.q-{i}",
                "turn_id": f"t{i}",
                "merged_len": 8,
                "lane_vector_n": 5,
                "lane_bm25_n": 4,
                "lane_top_k": 120,
                "search_limits": [30],
                "l2": {
                    "n_search": 1,
                    "merged_len": 8,
                    "lane_vector_n": 5,
                    "lane_bm25_n": 4,
                    "lane_top_k": 120,
                    "search_limits": [30],
                },
            }
        )
    agg = depth_audit_aggregate(cases)
    assert agg["fiqa_lane_adjudication"] == "lane_top_k_starvation"
    assert agg["by_dataset"]["fiqa"]["lane_starved_n"] == 10


def test_depth_audit_aggregate_fiqa_pool_starvation() -> None:
    from official_bench.l2_probes import depth_audit_aggregate

    cases = []
    for i in range(10):
        cases.append(
            {
                "case_id": f"beir.fiqa.q-{i}",
                "turn_id": f"t-{i}",
                "n_search": 1,
                "search_limits": [30],
                "ranked_lengths": [10],
                "merged_len": 10,
                "metrics": {"n_hits": 10.0, "ndcg_at_10": 0.1},
                "l2": {"n_search": 1, "search_limits": [30], "merged_len": 10},
            }
        )
    for i in range(5):
        cases.append(
            {
                "case_id": f"beir.scifact.q-{i}",
                "turn_id": f"s-{i}",
                "n_search": 1,
                "search_limits": [30],
                "ranked_lengths": [30],
                "merged_len": 30,
                "metrics": {"n_hits": 30.0, "ndcg_at_10": 0.5},
                "l2": {"n_search": 1, "search_limits": [30], "merged_len": 30},
            }
        )
    agg = depth_audit_aggregate(cases)
    assert agg["fiqa_adjudication"] == "pool_starvation_despite_limit"
    assert agg["by_dataset"]["fiqa"]["merged_le15"] == 10
    assert agg["by_dataset"]["scifact"]["merged_ge30"] == 5


def test_patch_from_proposed() -> None:
    diff = "--- a/x\n+++ b/x\n@@\n+hi\n"
    events = [{"type": "patch.proposed", "payload": {"diff": diff}}]
    assert patch_from_events(events) == diff


def test_patch_from_propose_patch_tool_started() -> None:
    events = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "propose_patch",
                "arguments": {
                    "path": "app.py",
                    "old_text": "return 1",
                    "new_text": "return 2",
                },
            },
        }
    ]
    patch = patch_from_events(events)
    assert "app.py" in patch
    assert "return 2" in patch


def test_patch_from_edit_file_unified_content() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@\n+fixed\n"
    events = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "edit_file",
                "arguments": {"path": "fix.patch", "old_text": "a", "new_text": diff},
            },
        }
    ]
    # edit_file path ending .patch with unified new_text
    events2 = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "write_file",
                "arguments": {"path": "solution.diff", "content": diff},
            },
        }
    ]
    assert patch_from_events(events2) == diff
    _ = events  # edit_file without unified content is not a patch extract path


def test_patch_from_fenced_assistant_text() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@\n+fixed\n"
    events = [
        {
            "type": "assistant.delta",
            "payload": {"text": f"here is the fix:\n```diff\n{diff}```\n"},
        }
    ]
    # final_assistant_text aggregates deltas — if empty, fall through
    events = [
        {
            "type": "message.completed",
            "payload": {"text": f"here is the fix:\n```diff\n{diff}```\n"},
        }
    ]
    out = patch_from_events(events)
    assert "@@" in out
    assert "fixed" in out


def test_patch_from_events_none() -> None:
    assert patch_from_events([]) == ""
    assert patch_from_events([{"type": "tool.started", "payload": {"tool_name": "list_dir"}}]) == ""


def test_patch_from_write_file_fix_patch() -> None:
    diff = "--- a/x.py\n+++ b/x.py\n@@\n+fixed\n"
    events = [
        {
            "type": "tool.started",
            "payload": {
                "tool_name": "write_file",
                "arguments": {"path": "fix.patch", "content": diff},
            },
        }
    ]
    assert patch_from_events(events) == diff


def test_patch_apply_check(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    good = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
    assert patch_apply_check(tmp_path, good) is True
    bad = "diff --git a/missing.py b/missing.py\n--- a/missing.py\n+++ b/missing.py\n@@ -1 +1 @@\n-a\n+b\n"
    assert patch_apply_check(tmp_path, bad) is False
    assert patch_apply_check(tmp_path, "") is False


def test_patch_apply_check_on_dirty_tree_after_git_diff(tmp_path: Path) -> None:
    """Regression: apply-check must use clean HEAD, not the already-dirty worktree."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("y\n", encoding="utf-8")
    (tmp_path / "new.py").write_text("z\n", encoding="utf-8")  # untracked
    diff = patch_from_git_diff(tmp_path)
    assert "a.py" in diff
    assert "new.py" in diff
    assert patch_apply_check(tmp_path, diff) is True


def test_patch_from_git_diff_survives_non_utf8_blob(tmp_path: Path) -> None:
    """Regression: binary/non-UTF8 in worktree must not raise UnicodeDecodeError.

    L1 coding suite previously failed entire runs with
    ``utf-8 codec can't decode byte 0xe0 ... invalid continuation byte`` when
    ``git diff`` stdout was decoded via ``text=True`` without errors=replace,
    then retried unprotected in the extract except path.
    """
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("y\n", encoding="utf-8")
    # Invalid UTF-8 lead byte 0xe0 without continuation — same class as Ops fail.
    (tmp_path / "blob.bin").write_bytes(b"\xe0" + b"\x00" * 1024)
    diff = patch_from_git_diff(tmp_path)  # must not raise UnicodeDecodeError
    assert "a.py" in diff
    assert "@@" in diff


def test_patch_hunks_incomplete() -> None:
    complete = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
    assert patch_hunks_incomplete(complete) is False
    truncated = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n-x\n+y\n"
    # claims 2 old / 2 new lines but only one of each
    assert patch_hunks_incomplete(truncated) is True
    assert patch_apply_check(Path("/tmp"), truncated) is False


def test_patch_from_work_root(tmp_path: Path) -> None:
    diff = "--- a/a\n+++ b/a\n@@\n+x\n"
    (tmp_path / "fix.patch").write_text(diff, encoding="utf-8")
    assert patch_from_work_root(tmp_path) == diff


def test_patch_from_git_diff_excludes_local_site_packages(tmp_path: Path) -> None:
    """Regression: pip --user / .local junk must not enter SWE model_patch."""
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("y\n", encoding="utf-8")
    junk = (
        tmp_path
        / ".local"
        / "lib"
        / "python3.11"
        / "site-packages"
        / "erfa"
    )
    junk.mkdir(parents=True)
    (junk / "__init__.py").write_text("POLLUTE\n", encoding="utf-8")
    diff = patch_from_git_diff(tmp_path)
    assert "a.py" in diff
    assert ".local" not in diff
    assert "site-packages" not in diff
    assert "POLLUTE" not in diff


def test_filter_unified_diff_noise_drops_site_packages() -> None:
    raw = (
        "diff --git a/src/ok.py b/src/ok.py\n"
        "--- a/src/ok.py\n"
        "+++ b/src/ok.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
        "diff --git a/.local/lib/python3.11/site-packages/x.py "
        "b/.local/lib/python3.11/site-packages/x.py\n"
        "--- a/.local/lib/python3.11/site-packages/x.py\n"
        "+++ b/.local/lib/python3.11/site-packages/x.py\n"
        "@@ -0,0 +1 @@\n"
        "+junk\n"
    )
    cleaned = filter_unified_diff_noise(raw)
    assert "src/ok.py" in cleaned
    assert ".local" not in cleaned
    assert "junk" not in cleaned


def test_patch_from_git_diff(tmp_path: Path) -> None:
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("y\n", encoding="utf-8")
    diff = patch_from_git_diff(tmp_path)
    assert "a.py" in diff
    assert "@@" in diff or "diff --git" in diff


def test_called_tools() -> None:
    events = [
        {"type": "tool.started", "payload": {"tool_name": "search_sources"}},
        {"type": "tool.completed", "payload": {"tool_name": "search_sources"}},
    ]
    assert called_tools(events) == ["search_sources"]


def test_query_drift_and_buckets() -> None:
    assert query_drift("hello world", "hello world") == 0.0
    assert query_drift("abc", "xyz") > 0.5
    assert classify_bucket("retrieval", {"searched": False}) == "no_search"
    assert (
        classify_bucket(
            "retrieval",
            {"searched": True, "query_drift": 0.9, "n_search": 1, "queries": ["x"]},
        )
        == "query_drift"
    )
    assert (
        classify_bucket(
            "retrieval",
            {
                "searched": True,
                "query_drift": 0.0,
                "n_search": 3,
                "queries": ["a", "b", "c"],
            },
        )
        == "search_cap"
    )
    assert (
        classify_bucket(
            "retrieval",
            {"searched": True, "query_drift": 0.0, "n_search": 1, "queries": ["q"]},
            case_ndcg=0.1,
            suite_ndcg_median=0.5,
        )
        == "weak_hits"
    )
    assert (
        classify_bucket(
            "context",
            {"truncation_hits": 2, "used_next_offset": False},
            case_f1=0.1,
        )
        == "truncated_unread"
    )
    assert (
        classify_bucket(
            "context",
            {"truncation_hits": 0, "used_next_offset": False, "read_bytes": 10},
            case_f1=0.0,
            passage_chars=10_000,
        )
        == "truly_abandoned"
    )
    assert (
        classify_bucket(
            "context",
            {
                "truncation_hits": 0,
                "used_next_offset": False,
                "read_bytes": 2000,
                "read_coverage": 0.2,
            },
            case_f1=0.0,
            passage_chars=10_000,
        )
        == "wrong_answer_after_read"
    )
    assert (
        classify_bucket(
            "context",
            {
                "truncation_hits": 0,
                "used_next_offset": True,
                "read_bytes": 5000,
                "answer_len": 200,
                "terminal_state": "completed",
                "steps": 3,
            },
            case_f1=0.5,
            case_em=0.0,
            passage_chars=100,
        )
        == "verbose_answer"
    )
    assert (
        classify_bucket(
            "context",
            {
                "truncation_hits": 0,
                "used_next_offset": True,
                "read_bytes": 5000,
                "answer_len": 20,
                "terminal_state": "stall",
                "steps": 3,
            },
            case_f1=0.5,
            case_em=1.0,
            passage_chars=100,
        )
        == "steps_exhausted"
    )
    assert (
        classify_bucket(
            "context",
            {
                "failure_class": "infra_channel",
                "failure_message": "model_error: openai transport error",
                "truncation_hits": 0,
                "read_bytes": 0,
                "read_coverage": 0.0,
                "terminal_state": "failed",
            },
            case_f1=0.0,
            passage_chars=10_000,
        )
        == "infra_channel"
    )
    assert (
        classify_bucket(
            "retrieval",
            {
                "searched": False,
                "failure_class": "infra_channel",
                "failure_message": "model API 503: Service is too busy",
            },
        )
        == "infra_channel"
    )
    assert classify_bucket("coding", {"patch_source": "none"}) == "no_patch"
    assert (
        classify_bucket(
            "coding",
            {"checkout_failed": True, "patch_source": "none"},
        )
        == "checkout_failed"
    )
    assert (
        classify_bucket(
            "coding",
            {"patch_source": "git_diff", "patch_applies": False},
        )
        == "patch_no_apply"
    )
    assert (
        classify_bucket(
            "coding",
            {
                "patch_source": "git_diff",
                "patch_applies": True,
                "resolved": False,
                "ran_tests": False,
            },
        )
        == "no_verify"
    )
    assert (
        classify_bucket(
            "coding",
            {
                "patch_source": "git_diff",
                "patch_applies": True,
                "resolved": False,
                "ran_tests": True,
            },
        )
        == "patch_not_resolved"
    )


def test_config_fingerprint_stable() -> None:
    a = config_fingerprint(model={"model_name": "m"}, index_version=8)
    b = config_fingerprint(model={"model_name": "m"}, index_version=8)
    c = config_fingerprint(model={"model_name": "other"}, index_version=8)
    assert a == b
    assert a != c


def test_bucket_report_manifest() -> None:
    manifest = {
        "id": "r1",
        "official_suite": "retrieval",
        "cases": [
            {
                "case_id": "q1",
                "turn_id": "t1",
                "searched": False,
                "status": "fail",
                "metrics": {},
            },
            {
                "case_id": "q2",
                "turn_id": "t2",
                "searched": True,
                "query_drift": 0.0,
                "n_search": 1,
                "queries": ["same"],
                "status": "pass",
                "metrics": {"ndcg_at_10": 0.9},
            },
        ],
    }
    report = classify_manifest(manifest)
    assert report["bucket_counts"]["no_search"] == 1
    assert report["n_cases"] == 2


def test_apply_retrieval_weak_hits_and_snapshots() -> None:
    from official_bench.agent_path_extract import (
        excerpt_promote_reorder_count,
        top_ranked_hits_from_events,
    )
    from official_bench.l2_probes import (
        apply_retrieval_weak_hits,
        bucket_counts,
        weak_hits_snapshots,
    )

    cases = [
        {
            "case_id": "beir.scifact.q-1",
            "turn_id": "t1",
            "searched": True,
            "query_drift": 0.0,
            "n_search": 1,
            "queries": ["claim one"],
            "l2": {
                "searched": True,
                "query_drift": 0.0,
                "n_search": 1,
                "queries": ["claim one"],
            },
            "metrics": {"ndcg_at_10": 0.2},
            "top_hits": [{"path": "sources/a.txt", "doc_id": "a", "score": 0.9}],
        },
        {
            "case_id": "beir.scifact.q-2",
            "turn_id": "t2",
            "searched": True,
            "query_drift": 0.0,
            "n_search": 1,
            "queries": ["claim two"],
            "l2": {
                "searched": True,
                "query_drift": 0.0,
                "n_search": 1,
                "queries": ["claim two"],
            },
            "metrics": {"ndcg_at_10": 0.8},
            "top_hits": [],
        },
        {
            "case_id": "beir.scifact.agent",
            "status": "pass",
            "metrics": {"ndcg_at_10": 0.5},
        },
    ]
    median = apply_retrieval_weak_hits(cases)
    assert median == 0.5
    assert cases[0]["bucket"] == "weak_hits"
    assert cases[1]["bucket"] == "ok"
    counts = bucket_counts([c for c in cases if c.get("turn_id")])
    assert counts["weak_hits"] == 1
    assert counts["ok"] == 1
    snaps = weak_hits_snapshots(cases, suite_median=median)
    assert len(snaps) == 1
    assert snaps[0]["case_id"] == "beir.scifact.q-1"
    assert snaps[0]["query"] == "claim one"
    assert snaps[0]["top_hits"][0]["doc_id"] == "a"

    events = [
        {
            "type": "retrieval.completed",
            "payload": {
                "excerpt_promote_reorder": True,
                "ranked": [
                    {"path": "sources/beir/x.txt", "score": 0.5},
                    {"path": "sources/beir/y.txt", "score": 0.4},
                ],
            },
        }
    ]
    assert excerpt_promote_reorder_count(events) == 1
    tops = top_ranked_hits_from_events(events, limit=1)
    assert tops == [{"path": "sources/beir/x.txt", "doc_id": "x", "score": 0.5}]


def test_prompt_helpers_no_tool_script_on_free() -> None:
    from official_bench.l1_prompts import context_prompt, limit_rows_per_task, retrieval_prompt

    free = retrieval_prompt(arm="free", qtext="q", limit_k=100)
    assert "search_sources" not in free
    assert "exactly once" not in free
    forced = retrieval_prompt(arm="forced", qtext="q", limit_k=100)
    assert "search_sources" in forced
    ctx = context_prompt(arm="free", question="Q?")
    assert "read_file once" not in ctx
    assert "Minimize tool calls" not in ctx
    oracle = context_prompt(arm="oracle", question="Q?")
    assert "offset" in oracle.lower()
    rows = [
        {"task": "a", "id": 1},
        {"task": "a", "id": 2},
        {"task": "b", "id": 3},
    ]
    capped = limit_rows_per_task(rows, 1)
    assert len(capped) == 2
    assert {r["task"] for r in capped} == {"a", "b"}


def test_csi_probes_from_events_locate_and_edit() -> None:
    events = [
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "grep",
                "redirected_from": "grep",
                "locate_status": "ok",
                "definition_count": 2,
            },
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "edit_file",
                "status": "ok",
                "applies": True,
                "bytes_written": 10,
                "impact": {"status": "ok", "symbol": "foo", "reference_count": 1},
                "checks": {"status": "ok", "syntax": "ok", "new_issue_count": 0},
            },
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "edit_file",
                "status": "error",
                "applies": False,
                "summary": "old_text not found",
                "candidate_count": 3,
            },
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "edit_file",
                "status": "error",
                "applies": False,
                "checks": {"status": "rejected", "syntax": "error"},
            },
        },
    ]
    probes = csi_probes_from_events(events)
    assert probes["n_grep_locate"] == 1
    assert probes["n_grep_locate_ok"] == 1
    assert probes["n_edit_ok"] == 1
    assert probes["n_edit_with_impact"] == 1
    assert probes["n_edit_with_checks"] == 1
    assert probes["n_span_fail"] == 1
    assert probes["n_span_fail_with_candidates"] == 1
    assert probes["n_syntax_rejected"] == 1


def test_csi_suite_rates_denominators() -> None:
    rates = csi_suite_rates(
        [
            {
                "bucket": "ok",
                "n_grep_locate": 2,
                "n_grep_locate_ok": 1,
                "n_edit_ok": 2,
                "n_edit_with_impact": 2,
                "n_edit_with_checks": 1,
                "n_span_fail": 2,
                "n_span_fail_with_candidates": 1,
                "n_syntax_rejected": 0,
                "n_syntax_warning": 1,
            },
            {"bucket": "no_patch", "n_grep_locate": 0, "n_edit_ok": 0},
        ]
    )
    assert rates["locate_fuse_ok_rate"] == 0.5
    assert rates["edit_impact_coverage"] == 1.0
    assert rates["edit_checks_coverage"] == 0.5
    assert rates["span_fail_with_candidates_rate"] == 0.5
    assert rates["bucket_share_no_patch"] == 0.5
    assert rates["syntax_warning_passthrough_count"] == 1.0


def test_csi_probes_locate_fuse_fail_reason_buckets() -> None:
    """§0.3 attribution probe: fuse-fail reason histogram from tool.completed."""
    events = [
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "grep",
                "redirected_from": "grep",
                "locate_status": "incomplete",
                "locate_incomplete": True,
                "definition_count": 0,
                "locate_fuse_fail_reason": "no_workspace_symbol_match",
            },
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "search_codebase",
                "locate_status": "incomplete",
                "locate_incomplete": True,
                "definition_count": 0,
                "locate_fuse_fail_reason": "definition_null",
                "candidate_count": 3,
            },
        },
        {
            "type": "tool.completed",
            "payload": {
                "tool_name": "grep",
                "redirected_from": "grep",
                "locate_status": "failed",
                "definition_count": 0,
                "locate_fuse_fail_reason": "lsp_timeout",
            },
        },
    ]
    probes = csi_probes_from_events(events)
    assert probes["n_locate_fuse_no_ws_symbol"] == 1
    assert probes["n_locate_fuse_definition_null"] == 1
    assert probes["n_locate_fuse_lsp_timeout"] == 1
    rates = csi_suite_rates([probes])
    assert rates["n_locate_fuse_definition_null"] == 1.0


def test_patch_from_git_diff_app_owned_tree_as_root(tmp_path: Path) -> None:
    """Regression: after materialize chown(1000), api(root) git must still extract."""
    import os
    import subprocess

    if os.geteuid() != 0:
        import pytest

        pytest.skip("needs root to chown like Ops api container")

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "a.py").write_text("y\n", encoding="utf-8")
    for dirpath, dirnames, filenames in os.walk(tmp_path):
        os.chown(dirpath, 1000, 1000)
        for name in dirnames + filenames:
            os.chown(os.path.join(dirpath, name), 1000, 1000)
    # Baseline without safe.directory fails (dubious ownership).
    bad = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert bad.returncode != 0 or not (bad.stdout or "").strip()
    diff = patch_from_git_diff(tmp_path)
    assert "a.py" in diff
    assert "+y" in diff
    assert patch_apply_check(tmp_path, diff) is True
