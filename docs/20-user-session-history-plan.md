# 20 — 登录用户会话历史与跨设备续聊（执行方案）

> **性质**：可排期的实施计划。  
> **落地状态（2026-07-15）**：U0–U2 代码已合入本仓库（端用户登录、`owner_user_id`、历史抽屉、迁移清空旧会话）；部署后跑 Alembic `0009` 并注册账号验收。  
> **产品目标**：登录后任意设备可看到**自己的**历史会话，交互内容与现网 Chat UI 一致，并允许继续对话且继承上下文。  
> **约束继承**：[17-execution-plan.md](17-execution-plan.md) 速率红线 R1–R5；不得拖慢 Turn 热路径。  
> **现状基线**（2026-07）：Session / turns / `session_transcripts` 已持久化；Web 可按 `session_id` 恢复聊天；Runtime 按 transcript 续上下文。**缺**端用户身份、session 归属、历史列表与读时鉴权。  
> **迁移策略**：允许**清空本功能上线前**的无主会话历史（见 §6）。

---

## 0. 需求对照

| # | 需求 | 方案落点 | 不做则失败的表现 |
|---|------|----------|------------------|
| 1 | 看到自己以前的历史，含交互内容；UI 一致 | `GET /sessions`（我的）+ 点选后走现有 `fetchSessionTurns` + `AgentChatPanel`；**不另做一套聊天渲染** | 有列表但打开后布局/组件不一致，或只有摘要没有 turn 文本 |
| 2 | 跟随登录用户 | `end_users` + cookie/JWT；`sessions.owner_user_id`；列表/读/写均按 owner 过滤 | 换设备看到别人会话，或登录与会话无绑定 |
| 3 | 允许继续，保留上下文 | 切换 `sessionId` 后发 Turn：Runtime `load_session_transcript` 既有路径；**不改 Agent loop** | UI 有历史但下一句模型像新会话 |
| 4 | Agent 性能 / 交互速率 | 身份校验与列表查询离热路径；禁止为首屏历史再调模型；列表分页 | 打开历史或登录拖慢 TTFB / 首 token |
| 5 | 异常与安全风险 | 读时 owner 校验、旧数据清零、失败可恢复、不泄露全库 | UUID 猜测读库、列表全量暴露、坏状态无法自救 |

**验收一句话**：用户 A 登录 → 历史列表只见 A → 点开旧会话 → 聊天区与平时同一套 UI、内容齐全 → 继续发送 → 模型带上该 session 的 rolling transcript。

---

## 1. 非目标（本方案否决 / 延期）

| 项 | 说明 |
|----|------|
| 公网多租户 SaaS / SSO 全家桶 | Phase 1–2 用本地账号即可；OAuth/SSO 单列 Phase 3 |
| 工作区按用户物理隔离 | 对话归属 ≠ 磁盘隔离；文件串数据风险见 §7，**不阻塞**本方案上线，产品文案需标明 |
| 改 Runtime Intake / 工具表 / Harness | 续聊已通，禁止借机改 Agent 主循环 |
| 历史列表内嵌全文预览（全 turns） | 列表只摘要；全文仅在打开会话后按现有 turns API 拉取 |
| 「恢复创建前完美字节一致的 prompt」 | compact / snip 后模型上下文可能短于 UI 可见 turns；产品接受，见 §7.3 |
| 兼容并展示上线前无主会话 | **明确允许清空**（§6），不做认领迁移 |

---

## 2. 现状与复用点

| 能力 | 位置 | 本方案用法 |
|------|------|------------|
| Session / Turn DDL | `packages/contracts/schemas/ddl/phase0.sql` 等 | 加 `owner_user_id`；外键 users |
| Turn 列表投影 | `GET /sessions/{id}/turns` + `useWorkbench` 恢复 | **打开会话后唯一 UI 数据源** |
| 聊天渲染 | `AgentChatPanel` / `turnHistory` | UI 一致：不换组件，只换 `sessionId` |
| 上下文继承 | `turn_controller` → `load_session_transcript` | 零改或仅日志；禁止在热路径加用户查询 |
| 当前鉴权 | `require_api_access`（共享 admin Basic） | **保留**给模型设置 / 运维；**新增**端用户鉴权，职责分离 |
| Web 会话解析 | `workbenchSession.tsx`（URL / localStorage） | 登录后：候选 session 必须通过 owner 校验；「历史」点选写 id + URL |

---

## 3. 目标架构

```text
┌─────────────┐     cookie/JWT      ┌─────────────┐
│  Web 登录    │ ─────────────────► │  api: users  │
└─────────────┘                     └──────┬──────┘
       │                                   │ owner_user_id
       │  GET /sessions (mine)             ▼
       │  GET /sessions/{id}/turns   ┌─────────────┐
       │  POST /sessions/{id}/turns  │  sessions   │──► turns / session_transcripts
       ▼                             └─────────────┘
┌─────────────┐                           │
│ Chat UI     │  sessionId 切换 / remount   │ 仅 session_id
│ (现有)      │                           ▼
└─────────────┘                     ┌─────────────┐
                                    │  runtime    │  load transcript → 续聊
                                    └─────────────┘
```

**原则**：归属与鉴权停在 **api**；runtime 仍只认 `session_id`。api 在 `POST .../turns` 前校验 owner，失败不进 runtime。

---

## 4. 数据模型与契约草案

### 4.1 新表 `end_users`（名称可在实现时定为 `users`）

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | UUID PK | |
| `username` | CITEXT UNIQUE | 登录名 |
| `password_hash` | TEXT | 仅存 hash（如 argon2/bcrypt） |
| `status` | VARCHAR | `active` / `disabled` |
| `created_at` / `updated_at` | TIMESTAMPTZ | |

管理员账号（现有 Basic `admin`）**不**进入此表；职责：模型配置、可选「清空孤儿会话」运维接口。

### 4.2 `sessions` 变更

| 列 | 说明 |
|----|------|
| `owner_user_id` | UUID NULL → NOT NULL（迁移策略见 §6：先清空旧会话再加 NOT NULL，或清空后只允许带 owner 的 insert） |

索引：`(owner_user_id, updated_at DESC)` 供列表。

`session_views`（若有）同步带 `owner_user_id` 或 join sessions，避免列表 N+1。

### 4.3 API 草案（均需端用户鉴权，除非注明）

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/auth/register` | 可选；若仅邀请制则改为 admin 创建用户 |
| `POST` | `/auth/login` | 返回 Set-Cookie（HttpOnly）或 token；Web 优先 Cookie 便于跨页 |
| `POST` | `/auth/logout` | |
| `GET` | `/auth/me` | 当前用户 |
| `GET` | `/sessions` | **我的**会话：分页 `limit`/`cursor`；字段见下 |
| `POST` | `/sessions` | 创建时强制 `owner_user_id = me` |
| `GET` | `/sessions/{id}` | **403** 若非 owner（杜绝猜 UUID） |
| `GET` | `/sessions/{id}/view` | 同上 |
| `GET` | `/sessions/{id}/turns` | 同上；供历史 UI |
| `POST` | `/sessions/{id}/turns` | 同上后再调 runtime |

列表项建议字段（摘要，禁止嵌套全量 messages）：

```text
id, default_scenario_id, status, created_at, updated_at,
turn_count, title, last_user_preview, last_turn_status
```

`title`：首条 `user_input` 截断（≤80 字）或后续可编辑；首版确定性截断即可，**禁止 LLM 生成标题**（速率）。

### 4.4 Admin / 运维

| 方法 | 说明 |
|------|------|
| 现有 admin Basic | 模型 provider 等不变 |
| 可选 `DELETE /admin/sessions/orphan-purge` | 清空 `owner_user_id IS NULL` 或迁移标记批次；§6 主路径也可用一次性 migration SQL |

Web 侧 admin Basic 与 end-user Cookie **并存策略**：fetch 拦截器按路径选凭证；会话/历史走用户 Cookie，`/admin/*` 仍走 Basic。

---

## 5. Web 体验（保证 UI 一致）

### 5.1 信息架构

| 入口 | 行为 |
|------|------|
| 未登录 | 访问工作台 → 引导登录（或登录后进工作台）；**不**再静默创建无主 session |
| 登录后 | 顶栏：用户名、「历史」、「新建会话」、「退出」；保留「复制链接」（仅本人打开有效） |
| 「历史」 | 抽屉/模态：分页列表（标题、时间、turn 数、预览）；点选 → `writeStoredSessionId` + navigate `?session=` + `WorkbenchProvider` 按 `sessionId` remount |
| 打开后 | **完全复用**现有 `useWorkbench` 拉 turns → `AgentChatPanel`；加载文案可沿用「正在加载会话历史…」 |
| 继续发送 | 现有 `POST .../turns`；后端 owner 校验通过后 runtime 拼 transcript |

### 5.2 UI 一致性硬约束

- 禁止为「历史模式」复制第二套气泡 / markdown / 工具状态组件。  
- 历史打开 = 普通会话打开；差异仅来源是「从列表选 id」还是「新建」。  
- `fetchSessionView` 仅作列表元数据可选增强，不替代 turns。

### 5.3 本地状态

| 键 | 变更 |
|----|------|
| `agent_platform_session_id` | 仍可缓存「上次打开」；进入时 `getSession` 若 403/404 → 清缓存并进历史或新建 |
| 新增 `agent_platform_user` | 仅缓存非敏感展示名（可选）；token 不进 localStorage（Cookie 优先） |

---

## 6. 上线前历史清空（明确允许）

**产品决定**：代码更新启用归属能力时，**可以并建议清空**此前产生的全部无主会话及相关行，避免「无主数据进列表 / 认领纠纷 / 半套兼容」。

### 6.1 清空范围（migration 一次性）

按 FK 顺序删除或 `TRUNCATE … CASCADE`（实施时以实际 FK 为准），至少包括：

- 与 session 关联的：`turn_views` / `session_views` / `session_transcripts` / runs / events 投影相关行 / `turns` / `sessions`
- **不删**：`model_provider_profiles`、资料索引、与 session 无关的配置表
- **工作区磁盘文件**：本方案**默认不动**（文件本就不按 session 隔离）；若需洁净工作区，运维另行备份后清理 `workspace/`（文档备注即可）

### 6.2 迁移步骤建议

1. 维护窗口：停写入（或短暂停 api/runtime）。  
2. Alembic revision：  
   - 创建 `end_users`；  
   - **purge** 旧 sessions 图谱；  
   - `sessions.owner_user_id UUID NOT NULL REFERENCES end_users(id)`；  
   - 建列表索引。  
3. 部署 api/web（需登录）。  
4. 创建首个业务用户（register 或 admin seed）。  
5. Smoke：登录 → 新建 → 一轮对话 → 登出 → 换浏览器登录 → 历史可见 → 打开 → 续聊有上下文。

### 6.3 回滚

- DB：保留 purge 前逻辑备份（pg_dump）至窗口结束。  
- 应用：双凭证兼容期内可 feature flag `USER_SESSION_AUTH=0` 回退旧行为（仅应急；flag 打开时禁止暴露全库列表）。

---

## 7. 异常与风险登记

| ID | 风险 | 等级 | 缓解 |
|----|------|------|------|
| R-A | 未做 owner 校验即提供列表 / GET | **高** | 列表强制 `WHERE owner_user_id = me`；所有 session 级读/写 403 |
| R-B | 共享「复制链接」被未授权打开 | **高** | 非 owner → 403；分享若需要，另做显式 share token（本方案不做） |
| R-C | 登录撞库 / 弱口令 | 中 | 密码哈希 + 登录限速；私有部署可关 register |
| R-D | Cookie CSRF | 中 | SameSite=Lax（或 Strict）+ 写操作 CSRF token（若 Cookie 会话）；API 纯 Bearer 则另论 |
| R-E | 列表/打开拖慢 Turn | 中 | 见 §8；历史 API 与 Turn 路径分离；禁止同步 LLM |
| R-F | UI turns 完整 vs transcript 已 compact | 低 | 文档与 UI 不承诺「模型所见 = 屏幕全文」；续聊以 transcript 为准 |
| R-G | 工作区文件跨用户可见 | **中高**（部署相关） | 本方案标明限制；单团队可信环境可接受；多用户公网必须另立项隔离 |
| R-H | 清空旧数据不可逆 | 中 | §6 备份窗口；产品预告 |
| R-I | 活跃 Turn 中途切换会话 | 低 | 切换时 remount；进行中 turn 不跨 session 续流；提示先完成或取消 |
| R-J | admin 与 end-user 凭证混淆 | 中 | 路径与依赖分离；前端勿用 admin 密码冒充用户登录 |
| R-K | 分页打爆 DB | 低 | `limit` 上限（如 50）；cursor 基于 `(updated_at, id)` |

---

## 8. 性能与速率红线（本方案专用）

继承 R1–R5，并补充：

| # | 规则 | 落地 |
|---|------|------|
| P1 | 登录态解析 ≤ 毫秒级 | JWT 验签或 session 表主键查找；**不**每请求打外部 IdP（Phase 1） |
| P2 | `GET /sessions` 只查摘要 | join `session_views` / 聚合 turn_count；**禁止** `SELECT` 全量 transcript |
| P3 | 打开历史 = 现有 turns 拉取 | 与今日「刷新同会话」同成本；可按页若 turns 极多（首版可一次拉全，设软上限告警） |
| P4 | **零**新增首 token 前模型调用 | 标题、摘要均确定性 |
| P5 | owner 校验不得进 runtime 热路径深逻辑 | api 门口一次 `SELECT owner_user_id`；可与 get_session 合并 |
| P6 | 历史抽屉懒加载 | 仅点击「历史」时请求列表；不要进入首页就拉全库 |
| P7 | 不影响 stub/live eval | eval 使用专用用户或 `AUTH` 旁路仅限 test profile，且不得在生产默认开启 |

**期望体感**：登录与打开历史对「点发送 → turn.accepted / 首 token」无附加等待；续聊 token 消耗与今日同 session 续跑一致（仍受既有 compact 约束）。

---

## 9. 冲刺拆分

### U0 — 迁移窗口与旧历史清空（P0）

| 项 | 内容 |
|----|------|
| **做什么** | Alembic：建用户表 → purge 无主会话图谱 → `owner_user_id`；运维备份说明写入本 §6 |
| **验收** | 库中无 `sessions` 孤儿；迁移可在空库/有旧数据库复现 |
| **速率** | 一次性离线；无热路径 |

### U1 — 端用户鉴权 + Session 归属（P0）

| 项 | 内容 |
|----|------|
| **改哪里** | `services/api` auth 模块；`resource/sessions.py`；`routers/sessions.py`；OpenAPI；Web login + 凭证 |
| **做什么** | register/login/logout/me；创建/读/写 session 绑 owner；未授权 401、非 owner 403 |
| **单测** | 用户 A 不能 GET/POST 用户 B 的 session；创建后 owner 正确 |
| **速率** | 🟢 门口一次查询 |
| **完成标准** | api-test 绿；无主创建路径关闭 |

### U2 — 历史列表 + 点选载入 + UI 一致续聊（P0）

| 项 | 内容 |
|----|------|
| **改哪里** | `GET /sessions`；Web 顶栏「历史」；`workbenchSession` 切换；`client.ts` |
| **做什么** | 分页列表；点选切换 sessionId；复用 turns 恢复与 Chat UI；新建归当前用户 |
| **单测 / 手工** | 跨浏览器：同用户见同一列表；打开后气泡与新建会话视觉一致；续聊验证模型记得上文（手工或 integration） |
| **速率** | 列表懒加载；摘要查询有索引 |
| **完成标准** | 需求 §0 五条人工验收通过 |

### U3 — 体验硬化（P1，可紧随）

| 项 | 内容 |
|----|------|
| 标题展示优化、空会话过滤、归档/软删 | |
| 登录限速、disable 用户 | |
| 可选：turns 过多时分段拉取 | |
| 文档：`contracts.md` / `07-domain-model.md` 补 owner 语义 | |
| **不做**：工作区隔离、SSO（除非单列） |

---

## 10. 票粒度清单（实施时勾选）

**U0**

- [x] 备份与维护窗口说明（运维） — 产品允许清空；部署前自行 pg_dump  
- [x] Alembic：`end_users` + purge + `sessions.owner_user_id` + 索引（`0009_phase1d_end_users`）  
- [x] 合约 DDL：`phase1d_end_users.sql`  

**U1**

- [x] 密码哈希与 login/logout/me  
- [x] FastAPI 依赖：`require_end_user` / `require_session_actor`；admin Basic 保留  
- [x] sessions/turns/runs 路由接入 owner 校验  
- [x] Web：登录页、退出  
- [x] api 单测：`test_end_user_auth` + integration routers  

**U2**

- [x] `GET /sessions` 分页摘要  
- [x] Web「历史」抽屉 + 点选切换  
- [x] 去掉「未登录静默 createSession」  
- [ ] 跨设备手工验收（登录 → 历史 → 续聊）  
- [x] runtime 无改动  

**U3**（可选后续）

- [ ] 软删/归档、标题编辑、登录限速  
- [ ] `07-domain-model` / OpenAPI 全文同步  

---

## 11. 验收闸

### 11.1 功能（需求 1–3）

1. 用户 A、B 各造 ≥2 会话；A 的「历史」不可见 B。  
2. A 打开旧会话：Chat 区组件与新建会话一致，turns 内容与当时一致（以 `turn_views.latest_output` / 历史项为准）。  
3. A 继续提问：回复体现上文（引用前几轮事实即可）；对应 session 的 `session_transcripts` 有增长。  
4. 登出后无法调 turns；换设备登录 A 仍见列表。  

### 11.2 速率（需求 4）

5. 登录后冷开历史抽屉：列表 P95 目标与普通 `GET` 同量级（私有部署经验值 &lt; 300ms，不含网络极端）。  
6. 打开会话后发 Turn：与改造前同 session 续聊相比，**不新增**同步模型调用；`turn.accepted` 不被历史 API 阻塞。  
7. `make runtime-test` / `make api-test` / 相关 web test 绿。  

### 11.3 风险（需求 5）

8. 非 owner 访问 `GET/POST /sessions/{id}/…` → 403（单测）。  
9. 迁移后库中无上线前旧 session（或仅存在于备份）。  
10. 风险表 R-A/R-B/R-G 在发布说明中有对应状态（R-G 若未隔离需写明「单租户可信环境假设」）。  

---

## 12. 建议工期（单人，估）

| 冲刺 | 工期 | 依赖 |
|------|------|------|
| U0 | 0.5 day | 维护窗口 |
| U1 | 2–3 days | U0 |
| U2 | 1.5–2 days | U1 |
| U3 | 1–2 days | U2 |

合计约 **1–1.5 周** 可达到需求 1–5 的 P0；不含工作区隔离与 SSO。

---

## 13. 决策摘要（已拍板写入方案）

| 决策 | 选择 |
|------|------|
| 上线前无主历史 | **允许清空**，不做认领 |
| Chat UI | **复用**现有 Workbench / AgentChatPanel |
| 上下文续聊 | **复用** `session_transcripts`，不改 Agent 主循环 |
| 身份 | Phase 1 本地 `end_users`；admin Basic 保留给运维 |
| 跨用户文件隔离 | **本方案不做**；发布说明披露 |
| 列表标题 | 确定性截断，不用 LLM |

---

## 14. 参考

- 领域：[07-domain-model.md](07-domain-model.md) Session / Turn  
- 体验 SLO：[11-product-experience.md](11-product-experience.md)  
- 速率与否决项：[17-execution-plan.md](17-execution-plan.md) §0  
- 现状续聊实现：`services/runtime/app/controller/turn_controller.py`（`load_session_transcript`）  
- Web 恢复：`services/web/src/shared/workbench/useWorkbench.ts`、`workbenchSession.tsx`
