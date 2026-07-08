from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# Approval policy labels (06 §4): never | on_write | always
ON_WRITE_TOOLS = frozenset(
    {"write_file", "edit_file", "apply_patch", "propose_patch", "draft_section", "update_outline"}
)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    requires_approval: bool = False
    timeout_s: float = 60.0


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_for_names(self, names: list[str]) -> list[ToolSpec]:
        return [self._tools[n] for n in names if n in self._tools]

    def to_openai_tools(self, names: list[str]) -> list[dict[str, Any]]:
        tools = []
        for spec in self.list_for_names(names):
            tools.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "input_schema": spec.parameters,
                }
            )
        return tools
