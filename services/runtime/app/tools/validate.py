"""工具调用参数校验与引用标记提取。

在 handler 执行前，用 JSON Schema（Draft 2020-12）对模型提交的 tool arguments 做确定性校验；
失败时返回结构化 ``invalid_arguments`` 载荷，成功返回 ``None``。全程毫秒级、不调用 LLM。
"""

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
    """校验单次 tool call 的 arguments 是否符合注册表中的 JSON Schema。

    参数:
        tool_name: 工具名，写入错误载荷便于前端/日志定位。
        arguments: 模型提交的原始参数（应为 dict）。
        parameters: 该工具在 registry 中声明的 JSON Schema；缺省按 ``{"type": "object"}`` 处理。

    返回:
        ``None`` 表示校验通过；否则返回含 ``error``/``summary``/``details``/``missing``/``expected``
        的 dict，executor 据此拒绝调用 handler（不进入业务逻辑）。
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
    """从 JSON Schema 提取面向模型的精简「期望形状」摘要。

    参数:
        schema: 工具的 parameters schema，或 ``None``。

    返回:
        含 ``type``、可选 ``required`` 与 ``properties`` 键名列表的 dict，供错误回显。
    """
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
    """从草稿或 patch 文本中提取引用标记 ID。

    支持 ``[cite:…]`` 与裸 ``cite:…`` 两种形式；ID 体可含 CJK（如 ``[cite:亮剑]``）。
    优先匹配方括号形式，避免与正文误匹配。

    参数:
        text: 待扫描的完整文本。

    返回:
        去重后的 ``cite:…`` 字符串列表，按首次出现顺序排列。
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
