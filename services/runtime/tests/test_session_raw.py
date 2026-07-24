"""HM2: raw snapshot helpers stay off the model path."""

from __future__ import annotations

from app.controller.session_raw import tools_fingerprint


def test_tools_fingerprint_stable() -> None:
    tools = [{"name": "read_file", "description": "a"}]
    assert tools_fingerprint(tools) == tools_fingerprint(tools)
    assert tools_fingerprint(tools) != tools_fingerprint([{"name": "write_file"}])
