# 16 — 登录用户会话历史（模块正文）

> **状态（2026-07）：U0–U2 已落地**（端用户登录、`sessions.owner_user_id`、历史抽屉、硬删除、迁移清空无主会话）。  
> **速率**：[13](13-rate-redlines.md) R1–R5；身份校验与列表离 Turn 热路径。  
> **关联**：私有资料库身份复用本文 `owner_user_id` → [31 §6](15-rag-and-sources.md)。

---

## 1. 产品口径

| 需求 | 落点 |
|------|------|
| 只看自己的历史 | `GET /sessions` 按 owner 过滤 |
| UI 与现网一致 | 点选后走现有 turns + `AgentChatPanel` |
| 续聊带上下文 | 切 `sessionId` → Runtime `load_session_transcript`；**不改 loop** |
| 可删 | `DELETE /sessions/{id}`（本人） |

**非目标（会话模块本身仍成立）：** 公网 SSO 全家桶；历史列表内嵌全文；认领上线前无主会话。  

**磁盘 / 作品隔离：** 不在本文扩写。对话归属（`owner_user_id`）≠ 作品根隔离；后者见 [`27-multi-tenancy`](27-multi-tenancy.md)（`work_id` / `work_root`，**划分默认开启** · 个人自动单默认 Work）。

---

## 2. 验收

用户 A 登录 → 列表只见 A → 打开旧会话 → 同一套聊天 UI → 继续发送 → 模型带该 session transcript。

部署：Alembic 含 `owner_user_id` 相关 revision；注册账号后手测上述路径。

---

## 3. 以后若改会话归属

改代码后只更新 **本文**；不要再开平行 `*-plan` 长文。若动资料 / 作品隔离，同步 [15](15-rag-and-sources.md) IX5 与 [27](27-multi-tenancy.md)。详细设计草稿见 git 旧版。
