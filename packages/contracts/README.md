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

## 版本化(F9)

契约整体使用一个 SemVer 版本(`pyproject.toml` 与 `python/pyproject.toml` 保持一致),
每次变更追加 [`CHANGELOG.md`](CHANGELOG.md) 条目:

- **patch**:仅文档/注释/描述,不改结构。
- **minor(向后兼容)**:新增事件类型、payload 新增**可选**字段、枚举新增值、
  REST 新增端点/可选参数。消费者(api 投影、web)必须容忍未知事件类型与未知枚举值。
- **major(破坏性)**:删除/重命名字段或事件、字段必填化、语义变化。
  需要双端锁步发布,并在 CHANGELOG 写明迁移顺序。

滚动升级约束(`deploy/compose/ha.yml` 双 runtime 副本):事件 schema 由**写侧**
(runtime)按自身镜像内的 schema 校验,新旧副本各自自洽;因此 minor 变更先升消费者
(api/web,容忍新字段)再升生产者(runtime)即可,无需停机。

双向防漂移:

- `scripts/codegen.sh`(CI)保证 web TS 类型 ⊆ `openapi/public.yaml`;
- `services/api/tests/test_openapi_contract.py` 保证 `public.yaml` ⊆ FastAPI 实际路由。

## 变更规则

1. 事件 `type`：同时改 `events/types.json`、`events/payloads/`（若已有则改对应文件 + `_index.json`）、`docs/adr/004-sse-turn-streaming.md`、`docs/contracts.md` §3。
2. 领域表：同时改 `ddl/phase0.sql` 或 `ddl/phase1_*.sql`、`docs/contracts.md` §7、`docs/07-domain-model.md` §7。
3. 管理面 API（模型供应商等）：同时改 `openapi/public.yaml`、`docs/contracts.md` §2.2、ADR-019。
4. 内部命令：同时改 `schemas/commands/*`、`docs/contracts.md` §8。
5. 对外 API：同时改 `openapi/public.yaml`、`docs/contracts.md` §2（Phase 0）与 §2.1（Phase 1 命令）；并运行 `scripts/codegen.sh` 同步 `services/web` TS 类型（ADR-018）。
6. Golden Turn：同时改 `eval/golden/`、`packages/contracts/eval/golden_turn.schema.json`、`docs/11-eval-and-golden-turns.md`。
