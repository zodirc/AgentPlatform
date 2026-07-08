# ADR-006: 能力以工具暴露（Tool-Centric）

## 状态

已接受（2025-06-30）

## 背景

`agent-langraph` 把 `retrieval`、`verify`、`writing`、`engineering` 等能力做成 LangGraph 流水线上的**节点**，由固定图按顺序触发。能力与编排耦合，新增能力需改图。

ADR-005 确定改用 agentic loop 后，需要一个统一的「能力扩展点」让模型按需调用。

## 决策

**所有可执行能力一律以「工具」形式暴露**，由模型在循环中按需调用：

1. 统一 `ToolSpec` 协议：`name / description / input_schema / side_effect / approval / handler`。
2. `description + input_schema` 视为 prompt 的一部分，是模型能否正确使用的关键。
3. `handler` 为 **async + 可流式**，长输出（命令 stdout）通过 `tool.delta` SSE 实时推送。
4. **副作用分级**：`read / write / exec / network / delegate`，对应不同审批策略（`never / on_write / always`；`delegate` 默认 `always`）。
5. 审批门绑定**单个工具调用**（替代旧 `policy_node` / `human_review_node` 终态节点）。
6. 旧的重型检索（routing/rerank/relevance_gate 等）作为 `search_codebase` 工具的**内部实现**保留，对循环只暴露干净接口。

详见 `docs/06-tools-and-context.md`。

## 理由

- 加能力 = 注册工具，循环与图零改动。
- 副作用分级 + 审批门让「写文件/跑命令」安全可控，且策略可按租户/环境配置。
- 检索从「强制阶段」变为「按需工具结果」，避免每轮塞无关 RAG 片段。

## 后果

### 正面

- 能力边界清晰、可独立测试（mock handler）。
- 安全模型统一（路径白名单 + 审批 + 租户隔离都挂在工具层）。

### 负面

- 工具 description / schema 的措辞成为质量关键，需要像产品文案一样维护与回归。
- 工具数量增长后需要工具选择/裁剪策略，避免 system prompt 过长。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 保留能力为图节点 | 与 ADR-005 矛盾，复制旧耦合 |
| 能力为 Provider 但由代码编排调用 | 仍是人编排，模型无法按需组合 |
