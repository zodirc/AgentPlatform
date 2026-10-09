"""Named outbound checks. Shell network stays off; this is the only egress path.

DNS is resolved and the addresses are checked again, so a name that later
points at a private or metadata address is still refused.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Callable
from urllib.parse import urlparse

from app.policy.matrix import host_emergency_denied
from app.settings import settings

_BLOCKED_NAMES = frozenset(
    {
        "localhost",
        "postgres",
        "redis",
        "model-gateway",
        "metadata",
        "metadata.google.internal",
    }
)

_BLOCKED_NETS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

URL_MAX_CHARS = 2048
_METADATA = "169.254.169.254"


def destination_blocked(host: str) -> bool:
    """True for loopback, RFC1918, link-local, metadata, and service names."""
    name = (host or "").strip().lower().rstrip(".")
    if not name or name in _BLOCKED_NAMES or name.endswith(".internal"):
        return True
    if name == _METADATA:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return any(address in net for net in _BLOCKED_NETS)


def host_allowlisted(host: str) -> bool:
    raw = str(getattr(settings, "egress_host_allowlist", "") or "")
    allowed = {item.strip().lower() for item in raw.split(",") if item.strip()}
    return (host or "").strip().lower() in allowed


def resolve_blocked(
    host: str,
    *,
    resolver: Callable[[str], list[str]] | None = None,
) -> str | None:
    """Return a reason when the name or any resolved address is internal."""
    if destination_blocked(host) or host_emergency_denied(host):
        return "blocked destination"
    lookup = resolver or _system_resolver
    try:
        addresses = lookup(host)
    except OSError:
        return "dns failed"
    for address in addresses:
        if destination_blocked(address):
            return "dns rebinding"
    return None


def _system_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return [str(info[4][0]) for info in infos]


async def proxy_request(method: str, url: str, *, body: str | None, headers: dict[str, str]):
    """The only outbound fetch. Credentials are already on ``headers`` from the broker."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        return await client.request(method, url, content=body, headers=headers)


def url_in_context(url: str, state: Any) -> bool:
    """The URL must already appear verbatim. A model-composed URL does not."""
    if not url:
        return False
    parts = [str(getattr(state, "turn_user_text", "") or "")]
    for message in getattr(state, "messages", None) or []:
        parts.append(str(message))
    return url in "\n".join(parts)


def classify_http(
    arguments: dict[str, Any] | None,
    *,
    window_taint: str,
    state: Any,
    resolver: Callable[[str], list[str]] | None = None,
) -> str:
    """allow, require_approval, or deny for one http_fetch call."""
    args = arguments or {}
    url = str(args.get("url") or "")
    if len(url) > URL_MAX_CHARS or not url:
        return "deny"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "deny"
    host = parsed.hostname
    blocked = resolve_blocked(host, resolver=resolver)
    if blocked:
        return "deny"
    method = str(args.get("method") or "GET").upper()
    has_body = bool(args.get("body"))
    if method != "GET" or has_body:
        return "require_approval"
    if not host_allowlisted(host):
        return "deny"
    from app.policy.scenario_policy import scenario_network_hosts

    scenario_hosts = scenario_network_hosts(str(getattr(state, "scenario_id", "") or ""))
    if scenario_hosts is not None and host.lower() not in scenario_hosts:
        return "deny"
    if window_taint == "external" and not url_in_context(url, state):
        return "require_approval"
    return "allow"
