# ADR-019: 模型供应商运行时配置（Web 管理 + DB 热生效）

## 状态

已接受（2026-07-02）

## 背景

ADR-003 将 `MODEL_*` 等变量定为 **`.env` → compose → Pydantic Settings（启动时读取）**。对个人自用场景，用户会**频繁更换**模型供应商与 API key；若每次修改 `.env` 并 `docker compose restart runtime`，则：

- 体验差，与「随时切换模型试用」的直觉不符；
- 进行中的 Turn 被粗暴中断（虽可接受，但应避免无谓重启）；
- 多供应商并存时 `.env` 堆叠多个 `*_API_KEY`，难以在 Web 工作台管理。

产品层（`11` 自用门槛）与 Web 设置入口（ADR-018）要求：**在浏览器中改配置，下一 Turn 即生效，无需重启容器**。

需在不破坏三服务边界、不把密钥暴露给前端的前提下，闭合「Web 入口 → 持久化 → runtime 注入」链路。

## 决策

### 1. 配置分层（Bootstrap vs Operational）

| 层级 | 存放 | 示例 | 变更频率 | 生效方式 |
|------|------|------|----------|----------|
| **Bootstrap（引导）** | `.env` → 容器环境变量 | `DATABASE_URL`、`APP_SECRET_KEY`、`INTERNAL_SERVICE_TOKEN`、加密主密钥 | 极低 | **重启**对应服务 |
| **Operational（运营）** | PostgreSQL `model_provider_profiles` | `provider`、`model_name`、API key、自定义 `base_url` | 高（自用切换供应商） | **不重启**；下一 Turn 生效 |

规则：

1. ADR-003 **仍然有效**于 Bootstrap 层；**不**用巨型 YAML，不把运营配置塞回 `.env`。
2. Phase 0 可仅用 `.env` 中 `MODEL_*` 作 **fallback**（DB 无激活配置时）；Phase 1 起 Web 管理面为**主路径**。
3. **禁止** web 容器读取或注入 `MODEL_API_KEY`；**禁止** web 将密钥 POST 至 runtime 内部接口。

### 2. 数据流（权威路径）

```text
web 设置页（脱敏展示）
  → api PUT/POST /api/v1/admin/model-providers/*（鉴权）
  → api 加密 api_key → UPSERT model_provider_profiles
  →（可选）pg_notify('provider_config_channel', profile_id)
  → runtime TurnController 受理 StartTurn 时：
       读 is_active=true 的 profile（或 env fallback）
       → 构造本轮 ModelGateway 客户端
       → 整轮 Turn 固定该配置
```

**禁止**：

- web → runtime 直连写密钥；
- Turn **执行中**切换 provider（Step 中途不换客户端）；
- 在 `turn_events`、结构化日志中输出完整 API key。

### 3. 表与写主权

表定义：`packages/contracts/schemas/ddl/phase1_provider_configs.sql`（Phase 1 迁移）。

| 表 | 主写方 | 主读方 | 说明 |
|----|--------|--------|------|
| `model_provider_profiles` | **api**（加密后写入） | **api**（脱敏列表）、**runtime**（解密后调模型） | 可存多条；**恰好一条** `is_active=true` |

字段要点：

- `api_key_ciphertext`：**api** 用派生自主密钥的 symmetric 加密（如 Fernet）；**runtime** 只读解密，用于 `ModelGateway`。
- `provider`、`model_name`、`base_url`（可选）：明文存库即可。
- `updated_at` / 单调 `config_version`：供 runtime 内存缓存失效。

### 4. 对外 API（管理面，Phase 1）

前缀：`/api/v1/admin/model-providers`（须 `AUTH_ENABLED` + admin 角色）。完整契约见 [`contracts.md`](../contracts.md) §2.2。

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 列表；`api_key` **仅脱敏**（如 `sk-••••abcd`） |
| `POST` | `/` | 新增 profile；body 含明文 key（HTTPS 传输） |
| `PUT` | `/{id}` | 更新；省略 `api_key` 表示不轮换密钥 |
| `PUT` | `/{id}/activate` | 设为当前生效；同事务内将其它行 `is_active=false` |
| `DELETE` | `/{id}` | 删除；**禁止**删除当前 `is_active` 唯一配置（须先激活另一条） |

响应使用标准 envelope（`contracts` §6）。**禁止**在 `GET` 响应中回显完整密钥。

### 5. runtime 加载与缓存

1. **默认**：每个 `StartTurn` 在 `TurnController` 入口查询 `model_provider_profiles WHERE is_active=true`。
2. **Fallback**：若无激活行，使用 `Settings` 中 `MODEL_PROVIDER` / `MODEL_API_KEY`（`.env` bootstrap）。
3. **缓存（可选）**：`ModelGatewayRegistry` 进程内缓存 + `config_version`；收到 `pg_notify` 或内部 `reload-provider-config` 时失效。**不得**无限期缓存而不校验版本。
4. **ready 检查**：`/health/ready` 在「DB 有激活 profile **或** env 有有效 `MODEL_API_KEY`」时通过；**不**因仅缺 env 但 DB 已配置而失败。

### 6. Web 设置页（ADR-018）

- 路由：`web` 设置页（如 `/settings/model`），调用上述 admin API。
- 保存成功后提示：**「下一 Turn 起生效」**；**不**提示重启容器。
- 进行中的 Turn 展示当时 provider/model（来自 `TurnView` 或事件元数据，Phase 1+ 可选字段）。

### 7. 安全

1. 传输：仅 HTTPS（gateway TLS）。
2. 存储：密文 + 主密钥来自 `APP_SECRET_KEY`（或专用 `CONFIG_ENCRYPTION_KEY` bootstrap 变量）。
3. 日志：redact `api_key`；model log 只记 `provider`、`model_name`。
4. 权限：admin API；Phase 1 可与 `ADMIN_PASSWORD` 单用户绑定。
5. eval/CI：使用 env fallback 或 mock provider，**禁止**把真实 key 写入 golden fixture。

### 8. Phase 边界

| 阶段 | 要求 |
|------|------|
| **Phase 0** | 仅 env `MODEL_*` fallback；可不实现 admin API |
| **Phase 1** | `model_provider_profiles` + admin API + Web 设置页；自用验收项（`11`） |
| **Phase 2+**（可选） | Session 级 provider 覆盖；ScenarioProfile 引用 `model_profile_id` |

## 理由

- **自用体验**：切换供应商是高频操作，重启 runtime 成本不合理。
- **架构一致**：Web → api（Command/Resource）→ DB → runtime 读，符合 ADR-001、ADR-009；runtime 仍独占 LLM 调用。
- **安全**：密钥不经 web 直投 runtime；加密落库 + 脱敏 API 可审计。
- **与 ADR-003 共存**：引导配置留 env；运营配置进 DB，不回到 800 行 YAML。
- **Turn 边界生效**：实现简单、语义清晰，与 Run:Turn 1:1 一致。

## 后果

### 正面

- 改 key / 换 provider 无需 `docker compose restart`。
- 可保存多条 profile（如「Claude 日常」「GPT 试用」）一键切换。
- `ModelGateway` 构造集中在一处，便于单测与 mock。

### 负面

- api 与 runtime 共享加密密钥材料（bootstrap env）；须严格保护 `APP_SECRET_KEY`。
- 多副本 runtime 时须依赖 DB 或 notify 保持缓存一致（Phase 0–2 单副本可忽略）。
- admin API 增加攻击面，必须强鉴权。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 仅 `.env` + 重启 runtime | 高频切换体验差 |
| 挂载 `.env` + inotify 热加载 | 权限与多副本同步复杂；密钥明文落盘 |
| web 直 POST runtime `/internal/set-key` | 破坏边界；密钥经 web 直达执行面 |
| Consul / etcd 动态配置 | Phase 0–2 已有 PostgreSQL，不新增组件 |
| Turn 中途热换 provider | checkpoint / 流式状态混乱；无明确收益 |

## 关联文档

- [`03-docker-runtime.md`](../03-docker-runtime.md) §3.1–3.3（Bootstrap vs Operational）
- [`05-agent-runtime.md`](../05-agent-runtime.md) §6（TurnController 加载配置）
- [`07-domain-model.md`](../07-domain-model.md) §7
- [`contracts.md`](../contracts.md) §2.2、§7.1
- [`11-product-experience.md`](../11-product-experience.md) §6
- [ADR-003](003-env-pydantic-settings.md) — Bootstrap 环境变量
- [ADR-009](009-protocol-four-layers.md) — 管理面 Resource/Command
- [ADR-018](018-web-frontend-stack.md) — Web 设置页
