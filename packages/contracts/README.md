# packages/contracts

跨服务契约（无业务逻辑）。人类可读索引：**[`docs/contracts.md`](../docs/contracts.md)**。

## 布局

```text
openapi/public.yaml                    # 对外 REST（已实施；codegen → services/web）
python/                                # agent-contracts Pydantic 包（api ↔ runtime 命令体）
schemas/
  ddl/phase0.sql
  ddl/phase1_provider_configs.sql      # ADR-019
  commands/
  events/
    envelope.json
    types.json
    payloads/                          # 按 type 的 payload schema（ADR-017）
  projections/
  errors.json
eval/
  golden_turn.schema.json
```

## 变更规则

1. 事件 `type`：同时改 `events/types.json`、`events/payloads/`（若已有则改对应文件 + `_index.json`）、`docs/adr/004-sse-turn-streaming.md`、`docs/contracts.md` §3。
2. 领域表：同时改 `ddl/phase0.sql` 或 `ddl/phase1_*.sql`、`docs/contracts.md` §7、`docs/07-domain-model.md` §7。
3. 管理面 API（模型供应商等）：同时改 `openapi/public.yaml`、`docs/contracts.md` §2.2、ADR-019。
4. 内部命令：同时改 `schemas/commands/*`、`docs/contracts.md` §8。
5. 对外 API：同时改 `openapi/public.yaml`、`docs/contracts.md` §2（Phase 0）与 §2.1（Phase 1 命令）；并运行 `scripts/codegen.sh` 同步 `services/web` TS 类型（ADR-018）。
6. Golden Turn：同时改 `eval/golden/`、`packages/contracts/eval/golden_turn.schema.json`、`docs/11-eval-and-golden-turns.md`。
