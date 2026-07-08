# Web Service

Static frontend (Vite + React + TypeScript → nginx). See ADR-018.

| Item | Value |
|------|-------|
| Port | `80` (container) |
| API | Relative `/api/v1` via gateway |
| UI | shadcn/ui（Radix + CVA，`components.json`） |

## 场景 Workbench（已实施）

| 路由 | 组件 | 说明 |
|------|------|------|
| `/writing` | `WritingWorkbench` | 大纲、章节、引用、patch diff |
| `/agent` | `AgentWorkbench` | 时间线、检索、产物视图 |
| `/interview` | `InterviewWorkbench` | 访谈 stub |
| `/settings/model` | `SettingsPage` | 模型供应商 Web 管理（ADR-019） |

实时：`shared/realtime/TurnStreamClient`（SSE）与 `TurnWebSocketClient`。

## Local dev

```bash
cd services/web
corepack enable
pnpm install
pnpm dev
```

Proxy `/api` to local api or compose stack.

## Build & test

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Docker multi-stage: `node:20-alpine` → `nginx:alpine`（见 `Dockerfile`）。
