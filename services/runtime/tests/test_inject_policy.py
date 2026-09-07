from __future__ import annotations

from uuid import uuid4

from app.policy.inject import inject_tool_result, remember_text_blocked
from app.tenant_context import bind_tenant_context, reset_tenant_context


def test_inject_redacts_bearer_token() -> None:
    out = inject_tool_result(
        tool_name="run_command",
        result={"stdout": "Authorization: Bearer abcdefghijklmnop", "status": "ok"},
    )
    assert "abcdefghijklmnop" not in str(out.get("stdout"))
    assert out["inject_policy"]["redacted"] >= 1


def test_inject_blocks_path_escape(tmp_path) -> None:
    tokens = bind_tenant_context(work_root=str(tmp_path), work_id=uuid4())
    try:
        out = inject_tool_result(
            tool_name="read_file",
            result={"path": "/etc/passwd", "content": "root:x:0:0", "status": "ok"},
        )
        assert out.get("status") == "error"
        assert out.get("content") == ""
    finally:
        reset_tenant_context(tokens)


def test_search_hits_tagged_retrieved_but_excerpt_not_blocked() -> None:
    excerpt = "the hidden retrieved excerpt body " * 3
    out = inject_tool_result(
        tool_name="search_sources",
        result={"hits": [{"path": "a.md", "excerpt": excerpt}], "retrieval": "hybrid"},
        turn_id=uuid4(),
    )
    assert out["hits"][0]["trust"] == "retrieved"
    assert remember_text_blocked(trust="user") is None
    assert remember_text_blocked(trust="retrieved")


def test_remember_blocks_only_explicit_retrieved_trust() -> None:
    assert remember_text_blocked(trust="user") is None
    err = remember_text_blocked(trust="retrieved")
    assert err and "retrieved" in err
