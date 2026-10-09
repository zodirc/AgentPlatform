"""Named outbound tool. Credentials come from the broker, not the arguments."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.policy.credentials import authorization_for, strip_model_secrets
from app.policy.egress import classify_http
from app.policy.taint import effective_window


async def http_fetch(
    url: str = "",
    method: str = "GET",
    body: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch one URL. The executor has already classified the call.

    The handler repeats the destination check so a direct call cannot skip it.
    """
    arguments = strip_model_secrets({"url": url, "method": method, "body": body})
    state = kwargs.get("state")
    window = effective_window(state) if state is not None else "external"
    verdict = classify_http(arguments, window_taint=window, state=state)
    if verdict == "deny":
        return {
            "status": "failed",
            "error": "destination blocked",
            "summary": "destination blocked",
        }
    parsed = urlparse(str(arguments.get("url") or ""))
    headers: dict[str, str] = {}
    token = authorization_for(parsed.hostname or "")
    if token:
        headers["Authorization"] = token
    request_body = arguments.get("body") or None
    request_method = str(arguments.get("method") or "GET").upper()
    if request_method == "GET":
        request_body = None
    from app.policy.egress import proxy_request

    try:
        response = await proxy_request(
            request_method,
            str(arguments.get("url") or ""),
            body=request_body,
            headers=headers,
        )
    except Exception as exc:
        return {"status": "failed", "error": str(exc), "summary": "http_fetch failed"}
    text = response.text[:32_000]
    return {
        "status": "ok",
        "url": str(arguments.get("url") or ""),
        "method": request_method,
        "status_code": response.status_code,
        "content": text,
        "summary": f"http_fetch {response.status_code}",
        "_taint": "external",
    }
