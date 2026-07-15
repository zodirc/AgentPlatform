from __future__ import annotations

from urllib.parse import urlparse

from app.model.gateway import ModelFatalError
from app.settings import settings

_DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "claude": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "gpt": "https://api.openai.com",
    "deepseek": "https://api.deepseek.com",
}


def normalize_base_url(url: str) -> str:
    return url.strip().rstrip("/")


def default_base_url_for_provider(provider: str) -> str:
    return _DEFAULT_BASE_URLS.get(provider.lower(), "https://api.openai.com")


def resolve_provider_base_url(provider: str, base_url: str | None) -> str:
    if base_url and base_url.strip():
        return normalize_base_url(base_url)
    return default_base_url_for_provider(provider)


def build_model_egress_allowlist() -> set[str]:
    allowed: set[str] = {normalize_base_url(u) for u in _DEFAULT_BASE_URLS.values()}
    for raw in (settings.anthropic_base_url, settings.openai_base_url):
        if raw and raw.strip():
            allowed.add(normalize_base_url(raw))
    for part in settings.model_egress_allowlist.split(","):
        piece = part.strip()
        if piece:
            allowed.add(normalize_base_url(piece))
    return allowed


def _host_key(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.netloc or parsed.path).lower()
    return host.split("@")[-1]


def is_model_egress_allowed(provider: str, base_url: str | None) -> bool:
    if not settings.model_egress_enforce:
        return True
    if settings.model_mode in {"stub", "recorded"}:
        return True
    resolved = resolve_provider_base_url(provider, base_url)
    allowed = build_model_egress_allowlist()
    if resolved in allowed:
        return True
    resolved_host = _host_key(resolved)
    return any(_host_key(item) == resolved_host for item in allowed)


def ensure_model_egress_allowed(provider: str, base_url: str | None) -> str:
    """Return normalized base URL or raise ModelFatalError (fail closed, no outbound)."""
    resolved = resolve_provider_base_url(provider, base_url)
    if is_model_egress_allowed(provider, base_url):
        return resolved
    raise ModelFatalError(
        f"model egress blocked: base_url={resolved!r} is not in MODEL_EGRESS_ALLOWLIST "
        f"(or defaults / ANTHROPIC_BASE_URL / OPENAI_BASE_URL)"
    )
