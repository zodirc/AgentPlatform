# 契约索引

跨服务契约的人类可读入口。机器源在 [`packages/contracts`](../packages/contracts/)；冲突时 **代码与 JSON Schema > 本文**。

## 1. 源与防漂移

| 源 | 路径 | 消费者 |
|----|------|--------|
| 对外 REST | `packages/contracts/openapi/public.yaml` | web codegen · `test_openapi_contract.py` |
| 事件 JSON Schema | `packages/contracts/schemas/events/` | runtime 写侧 · api 投影 |
| 命令 JSON + Pydantic | `packages/contracts/schemas/commands/` · `python/agent_contracts` | api ↔ runtime |
| Golden Turn | `packages/contracts/eval/golden_turn.schema.json` | eval/golden YAML |
| **Ops 评测 manifest** | `packages/contracts/eval/ops_run_manifest.schema.json` | L1 `RunSession.finish` · baseline · Ops 页 |
| DDL | `packages/contracts/schemas/ddl/` | postgres |
| 错误码 | `packages/contracts/schemas/errors.json` | api |

双向防漂移：`scripts/codegen.sh`（web ⊆ OpenAPI）；`services/api/tests/test_openapi_contract.py`（OpenAPI ⊆ FastAPI）；`packages/contracts/tests/test_ops_manifest_schema.py`（Ops manifest ⊨ schema）。

版本规则见 [`packages/contracts/README.md`](../packages/contracts/README.md)。

## 2. 对外 REST（Phase 0）

权威：`openapi/public.yaml`。叙述：[事件与契约](core/events.md) · [架构](core/architecture.md)。

### 2.1 Phase 1 命令面

内部命令体（StartTurn / CancelTurn / …）走 `schemas/commands/*`，不进公网 OpenAPI。

### 2.2 管理面

模型供应商等管理 API 仍以 `public.yaml` 为准；变更同步 ADR-019。

## 3. 事件

信封 + `type` 枚举 + 按 type 的 payload：`schemas/events/`。管道图见 [事件与契约](core/events.md)。

Ops 旁路事件（如 `retrieval.completed`）给评测卡，**不进**模型组窗。

## 4. Ops 评测结果契约

`ops_run_manifest.schema.json` 锁住 `RunSession.finish` 产出，防止 Ops 页 / CI / baseline 因键漂移误读。

必填：`id` · `suite=official` · `official_suite` ∈ {retrieval, retrieval_zh, context, coding} · `status` · `created_at` · `summary` · `cases` · `metrics`。

指标键（可选，有则须在 [0,1] 的比率类）：

| 套件 | 主指标 |
|------|--------|
| coding | `resolve_rate`（harness 官方）· `patch_rate`（辅助） |
| retrieval / retrieval_zh | `ndcg_at_k` · `recall_at_k` · `map_at_k` |
| context | `agent_f1` · `agent_em` |

**P0 验收规则**：`official_suite=coding` 且 `result.harness=true` 且 `status=completed` 时，`metrics.resolve_rate` **必须**存在，且 **不得**带 `metrics.harness_error`。Harness 失败必须 `status=failed`。

指针：`latest_retrieval.json` / `latest_retrieval_zh.json` / `latest_context.json` / `latest_coding.json` 不得互相覆盖。

## 5. 评测路径纪律

Ops 验收唯一路径是 **L1 agent-path**（`eval_path=agent`）：产品 Session/Turn → 真实工具 → 从事件抽结果 → 官方指标。禁止 dry / skip-api 空补丁冒充效果分。

```text
/official
  → 拒非 agent 路径
  → retrieval / retrieval_zh / context / coding
       ├ 检索：search_sources → 多轮 RRF 融合 → nDCG/R/MAP
       ├ 上下文：passage.md → 终答 Answer: → F1/EM
       └ 编码：checkout → AST wait_ready（仅评测）→ sweb 解题改道
               → git_diff → SWE harness resolve（无 resolve 则 failed）
```

细节：[工作台 · Ops Bench](topics/workbench.md) · [分数入账图](assets/ops/score-snapshot-zh.png) · [工具与上下文 §2](core/tools-and-context.md) · [架构 §6](core/architecture.md)。合入门禁是另一条链：[CI 证明](assets/ops/ci-proof-zh.png)。  
现行冒烟日记：[`RESULTS.md`](../eval/official/baseline/RESULTS.md)（第6轮 coding 4/5；不升 SCORECARD 主栏）。

## 6. Golden Turn

`eval/golden_turn.schema.json` + `eval/golden/**`。证明接口与 loop 不炸，**不能**冒充生产效果。

## 7. 领域表

DDL 在 `schemas/ddl/`。对象与状态机见 [架构 §3](core/architecture.md)。

## 8. 内部命令

`schemas/commands/*` 与 `python/agent_contracts/commands.py` 必须同步（`test_commands_schema_sync.py`）。
