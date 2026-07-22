# ADR-021: 多租户作为 Work 作用域绑定（非编排 · 默认开启）

## 状态

已接受（2026-07-22）— 设计与落地见 [`docs/27-multi-tenancy.md`](../27-multi-tenancy.md)。  
**落地：** MT0–MT5c + MT7（`make up-ha`）已合入。**否决 MT6**（Org / 作品显式 share）。MT5c = 检索硬 ACL、deny 证明、Admin/Sources 绑 Work、TenantContext 全字段。

## 背景

平台已具备：`sessions.owner_user_id`（对话归属）、Work-over-Session（书稿不随会话拆）、RAG「热路径不建索引 / 否决 LLM-ACL」。此前部署仍是 **单 `WORKSPACE_ROOT` ≡ 全世界**，多用户同栈时资料与书稿无法证明隔离。

若把多租户做成可关特性、loop 内策略、或按 `session_id` 建索引，会同时破坏：成熟 Agent「一个打开的世界」心智、R1–R5、以及「落地即进阶」的产品方向。

## 决策

1. **多租户 = 作用域绑定**：在 StartTurn / Intake 边界解析并冻结 `TenantContext`（`tenant_id`、`work_id`、`work_root`…）；`AgentEngine` while **零租户业务分叉**。
2. **隔离主键**：执行用 `work_id` → `work_root`；归属用 `tenant_id` / `owner_id`；**禁止** `session_id` 当隔离键。
3. **默认开启，不是运维开关**：不设用户/运维主开关 `TENANT_MODE`。个人自用与 CI 通过**自动创建并绑定唯一默认 Work**（`work_root` 可认领今日 `/workspace`）保持零仪式；谓词与沙箱始终在代码路径上。
4. **ACL 只走确定性路径**：路径沙箱 + 检索/记忆服务端注入谓词；**否决 LLM-ACL**。
5. **写作 / RAG / 记忆 / 委派** 全部挂同一 `work_root`；相对路径语义不变（复用 docs/23）。
6. **否决 Org / 作品显式 share / 多作品切换 UI**：多人 = 各开各的默认 Work；一账号对齐主流 Agent「一个打开的世界」+ 多 Session。
7. **分期 MT\***（见 docs/27）；扩容（多副本）与划分解耦。

## 理由

- 与成熟 Agent（单 project 根、对话可换、权限在平台）同构  
- 「有设计却默认关」会变成第二套世界，长期分叉；默认开 + 自动单 Work 才是真进阶  
- 满足 R1–R5：解析毫秒级；单默认 Work 可回归今日体感  
- 为 IX5/RE4 与「一账号一默认世界」提供同一结构  

## 后果

### 正面

- 可证明的 deny；多用户同栈可信  
- 无「忘了开开关」的半吊子部署  
- 个人 Web 仍可零仪式  

### 负面

- 迁移日必须认领/创建默认 Work（一次）；不能靠 mode=off 永久逃避  
- eval 夹具需 per-work（或等价隔离）  
- 逻辑多租户 ≠ 内核/集群级硬隔离（明确非目标）  

### 对速率与逻辑

- 热路径仅 PK/缓存解析 + 谓词；无额外 LLM  
- 工具名与 loop 语义不变  

## 备选方案

| 方案 | 结论 |
|------|------|
| 默认 `TENANT_MODE=off` | **否决（修订）**：与「产品进阶默认开启」冲突；易永久分叉 |
| 每租户独立部署 | 延后：运维重 |
| Session 级目录隔离 | 否决：与 ADR-020 冲突 |
| LLM 每问做 ACL | 否决：R2 + 不可证明 |

## 关联

- `docs/27-multi-tenancy.md`（正文 · §0.0 产品立场）  
- `docs/15` §6 · `docs/16` · `docs/23` §11 · `docs/17`  
- `docs/13` R1–R5 · ADR-014 · ADR-020  
