from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


def validate_tool_arguments(
    *,
    tool_name: str,
    arguments: Any,
    parameters: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a structured invalid_arguments payload, or None when valid.

    Kept deterministic and millisecond-scale (no LLM). Handlers are not called on failure.
    """
    if not isinstance(arguments, dict):
        return {
            "error": "invalid_arguments",
            "tool_name": tool_name,
            "summary": f"Tool {tool_name} arguments must be a JSON object",
            "details": [f"got {type(arguments).__name__}"],
            "missing": [],
            "expected": _expected_summary(parameters),
        }

    schema = parameters if isinstance(parameters, dict) and parameters else {"type": "object"}
    try:
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))
    except SchemaError as exc:
        return {
            "error": "invalid_arguments",
            "tool_name": tool_name,
            "summary": f"Tool {tool_name} has an invalid parameter schema",
            "details": [str(exc.message)],
            "missing": [],
            "expected": _expected_summary(schema),
        }

    if not errors:
        return None

    details: list[str] = []
    missing: list[str] = []
    for err in errors[:12]:
        path = ".".join(str(p) for p in err.absolute_path) or "$"
        details.append(f"{path}: {err.message}")
        if err.validator == "required":
            required_props = err.validator_value
            if isinstance(required_props, list):
                for req in required_props:
                    if req not in arguments:
                        missing.append(str(req))
            elif err.message.startswith("'") and "' is a required property" in err.message:
                missing.append(err.message.split("'")[1])

    missing_unique = list(dict.fromkeys(missing))

    return {
        "error": "invalid_arguments",
        "tool_name": tool_name,
        "summary": (
            f"Tool {tool_name} rejected invalid arguments"
            + (f" (missing: {', '.join(missing_unique)})" if missing_unique else "")
        ),
        "details": details,
        "missing": missing_unique,
        "expected": _expected_summary(schema),
    }


def _expected_summary(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object"}
    props = schema.get("properties")
    required = schema.get("required")
    out: dict[str, Any] = {"type": schema.get("type", "object")}
    if isinstance(required, list):
        out["required"] = [str(r) for r in required]
    if isinstance(props, dict):
        out["properties"] = sorted(str(k) for k in props.keys())
    return out


def extract_citation_ids(text: str) -> list[str]:
    """Find ``[cite:…]`` / bare ``cite:…`` markers in drafted or patched text.

    IDs may include CJK (e.g. ``[cite:亮剑]``).
    """
    import re

    if not text:
        return []
    found: list[str] = []
    # Prefer bracketed form; allow unicode letters/numbers in the id body.
    patterns = (
        r"\[cite:([^\]]+)\]",
        r"(?<!\[)cite:([\w./\-]+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.UNICODE):
            body = match.group(1).strip().rstrip("].),;，。；")
            if not body:
                continue
            cid = body if body.startswith("cite:") else f"cite:{body}"
            if cid not in found:
                found.append(cid)
    return found
