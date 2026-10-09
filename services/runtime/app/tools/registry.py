"""工具契约与注册表。

ToolSpec 是进模型的 tools[] 条目 + 本地 handler；ToolRegistry 仅做名字索引。
审批策略标签与粘性集合供 ToolExecutor / tool_scope 共用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# 审批策略标签（never | on_write | always）中「写盘类」工具名集合。
ON_WRITE_TOOLS = frozenset(
    {"write_file", "edit_file", "apply_patch", "propose_patch", "draft_section", "update_outline"}
)

# 同 Turn 内用户批准一次写盘后，下列工具可免再审（多文件连改 UX）。
WRITE_APPROVAL_STICKY_TOOLS = ON_WRITE_TOOLS | frozenset({"rename_file"})

# 评测无人值守可预批准 shell；交互 Turn 仍走命令前缀允许列表。
EXEC_APPROVAL_STICKY_TOOLS = frozenset({"run_command"})


@dataclass
class ToolSpec:
    """单条工具契约：schema 进模型，handler 在本进程执行。

    属性:
        name: 工具名（模型 tool_use 与事件里的标识）。
        description: 给模型的英文 how-to（勿当维护者注释改语义）。
        parameters: JSON Schema，映射为 input_schema。
        handler: async 执行体，返回可序列化的 result dict。
        requires_approval: 执行前是否打断等待用户批准。
        timeout_s: 单次调用墙钟上限（秒）。
    """

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[dict[str, Any]]]
    requires_approval: bool = False
    timeout_s: float = 60.0
    sink_class: str = ""
    result_taint: str = ""
    dynamic: bool = False
    definition_hash: str = ""


def _refuse_registration(name: str, reason: str) -> None:
    from app.policy.audit import append_security_log

    append_security_log(
        {
            "decision": "deny",
            "reason": "registration refused",
            "detail": reason,
            "tool_name": name,
            "sink_class": "",
        }
    )


class ToolRegistry:
    """按名称存放 ToolSpec 的进程内注册表。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        """注册或覆盖同名工具。未声明 sink 的名字拒绝注册。

        动态工具的定义哈希变了就下线，等重新审核后才能再注册。
        """
        from app.policy.definition_lock import accept_dynamic, definition_hash
        from app.policy.matrix import declared_class

        sink, taint = declared_class(spec.name)
        if not spec.sink_class:
            spec.sink_class = sink
        if not spec.result_taint:
            spec.result_taint = taint
        if not spec.sink_class:
            _refuse_registration(spec.name, "undeclared sink")
            raise ValueError(f"tool {spec.name} has no sink_class")
        digest = definition_hash(
            name=spec.name,
            description=spec.description,
            parameters=spec.parameters,
        )
        if spec.dynamic and not accept_dynamic(spec.name, digest):
            _refuse_registration(spec.name, "definition changed")
            raise ValueError(f"tool {spec.name} definition changed; offline until re-review")
        spec.definition_hash = digest
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        """按名查找工具；不存在返回 None。

        参数:
            name: 工具名。
        """
        return self._tools.get(name)

    def list_for_names(self, names: list[str]) -> list[ToolSpec]:
        """按给定名字顺序取出已注册工具（跳过未知名）。

        参数:
            names: 期望的工具名列表（通常来自 Profile.tool_names）。
        """
        return [self._tools[n] for n in names if n in self._tools]

    def to_openai_tools(self, names: list[str]) -> list[dict[str, Any]]:
        """导出模型网关所需的 tools[] 载荷（name / description / input_schema）。

        参数:
            names: 要导出的工具名子集。

        返回:
            可直接塞进模型请求的 dict 列表。
        """
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
