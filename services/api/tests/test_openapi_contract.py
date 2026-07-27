"""F9 (docs/35): public.yaml must stay a subset of the real FastAPI surface.

codegen.sh already guarantees the web client types match public.yaml
(TS <= yaml). This closes the other direction: every path+method promised in
public.yaml must exist on the app (yaml <= FastAPI), so the handwritten
contract cannot silently drift from the implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PUBLIC_YAML = _REPO_ROOT / "packages" / "contracts" / "openapi" / "public.yaml"

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


def _load_app():
    sys.modules.setdefault("asyncpg", MagicMock())
    from app.main import app

    return app


def test_public_yaml_paths_exist_in_app() -> None:
    spec = yaml.safe_load(_PUBLIC_YAML.read_text())
    server_prefix = spec["servers"][0]["url"].rstrip("/")

    app = _load_app()
    openapi_paths: dict[str, set[str]] = {
        path: {m for m in item if m in _HTTP_METHODS}
        for path, item in _load_app().openapi()["paths"].items()
    }
    # Websocket routes never appear in openapi(); compare against raw routes.
    # Newer FastAPI wraps included routers lazily, so unwrap those too.
    from starlette.routing import WebSocketRoute

    ws_paths: set[str] = set()
    for route in app.routes:
        if isinstance(route, WebSocketRoute):
            ws_paths.add(route.path)
            continue
        inner = getattr(route, "original_router", None)
        if inner is None:
            continue
        prefix = getattr(getattr(route, "include_context", None), "prefix", "")
        for sub in inner.routes:
            if isinstance(sub, WebSocketRoute):
                ws_paths.add(f"{prefix}{sub.path}")

    missing: list[str] = []
    for path, item in spec["paths"].items():
        full_path = f"{server_prefix}{path}"
        methods = {m for m in item if m in _HTTP_METHODS}
        if not methods:
            # Method-less entry in yaml (e.g. the /ws websocket path).
            if full_path not in ws_paths and full_path not in openapi_paths:
                missing.append(full_path)
            continue
        if full_path in ws_paths:
            continue
        actual = openapi_paths.get(full_path)
        if actual is None:
            missing.append(full_path)
            continue
        for method in methods - actual:
            missing.append(f"{method.upper()} {full_path}")

    assert not missing, (
        "public.yaml promises routes the API does not implement "
        f"(update packages/contracts/openapi/public.yaml): {sorted(missing)}"
    )
