# ADR-018: Web 前端技术栈（Vite + React + TypeScript + nginx 静态部署）

## 状态

已接受（2026-07-02）

## 背景

`services/web` 在 ADR-001 中定义为独立静态前端容器，但此前未在 ADR 或 `04-development-standards` 中锁定具体框架。`03-docker-runtime` §5.4 仅列举「Next.js 或等价框架」等方向性表述，实施时易出现：

- 生产镜像引入 Node 运行时，增大 VM 内存占用与配置面
- API 基址硬编码 host/port，与 gateway 反代模型冲突
- 前端类型与 `packages/contracts` 脱节
- SSE 消费在各场景重复实现，难以保证重连与乐观 Cancel 一致

产品需求（`11`、`10`）要求：SSE 流式、双场景布局（writing / agent）、diff 审阅、Stop 乐观 UI、断线重连。部署约束（`03`）要求：Docker 验收、web 容器轻量、配置入口以 `.env` 为主且 web 尽量不依赖运行时环境变量。

## 决策

### 1. 核心选型

| 层 | 选型 | 说明 |
|----|------|------|
| 语言 | **TypeScript** 5+ | 与 contracts codegen 对齐 |
| UI 框架 | **React** 18+ | 生态成熟；diff / 编辑器组件丰富 |
| 构建 | **Vite** 6+ | 快速 dev/build；产物为静态 `dist/` |
| 包管理 | **pnpm** | 仅 build stage；lockfile 入库 |
| 样式 | **Tailwind CSS** + **shadcn/ui**（Radix primitives） | 双场景共享组件库 |
| REST 数据 | **TanStack Query** | Session / Turn / TurnView |
| SSE | **`shared/realtime/`** 自研封装 | 统一 cursor、重连、乐观 Stop |
| 类型生成 | **openapi-typescript** 等 | 从 `packages/contracts` codegen |
| 生产部署 | **nginx:alpine** 托管 `dist/` | **禁止**生产容器常驻 Node 进程 |

### 2. 部署与配置

1. **多阶段 Docker**：`node:20-alpine` 构建 → `nginx:alpine` 运行；Node 仅出现在 build stage。
2. **API 基址**：生产与容器内一律使用相对路径 **`/api/v1`**，经 gateway 反代至 `api`；**禁止**在镜像内写死 `localhost:8000`。
3. **web 无运行时配置**：web 容器不读取 `.env` 业务变量；鉴权与路由由 gateway + api 承担。
4. 本地开发：`pnpm dev` + Vite `server.proxy` 将 `/api` 转发至本地或 compose 中的 `api:8000`（见 `03` §7.2）。
5. **设置页**：`src/settings/` 调用 `api` admin 模型供应商接口（ADR-019）；**禁止**在前端存明文 API key（仅表单提交与脱敏展示）。

### 3. 目录与模块边界

```text
services/web/
├── Dockerfile
├── package.json
├── pnpm-lock.yaml
├── vite.config.ts
├── nginx.conf
└── src/
    ├── shared/
    │   ├── api/            # codegen 类型 + fetch 封装
    │   └── realtime/       # TurnStreamClient（SSE）
    └── scenarios/
        ├── writing/        # 大纲、diff、引用侧栏
        └── agent/          # 时间线、工具轨、终端输出
```

规则：

- **禁止** web import `api` / `runtime` Python 代码；仅 HTTP + 生成的 TS 类型。
- **禁止**在组件内维护 Turn 阶段状态机；状态 = `TurnView` 投影 + SSE `sequence` cursor（`09` §5）。
- 编辑器（CodeMirror 6 或 Monaco）**按场景懒加载**，避免首屏体积膨胀。
- 新增场景 = `scenarios/<id>/` + Projection 消费，不改共享 realtime 协议。

### 4. SSE 客户端抽象

封装 `TurnStreamClient`，对外统一接口；内部可按需切换：

- 默认同源 **`EventSource`**（Cookie 鉴权、无自定义 Header 时）
- **`fetch` + `ReadableStream`**（需 Bearer Header 等 `EventSource` 不支持的场景）

重连须支持 `Last-Event-ID` / `since_sequence`（ADR-004、`09` §4.2）。

### 5. Phase 0 与 Phase 1+

| 阶段 | web 交付 | 状态 |
|------|----------|------|
| **Phase 0** | Dockerfile build → nginx；gateway → web 路由 | ✅ |
| **Phase 1+** | Vite + React；`shared/realtime`；writing / agent / interview Workbench；模型设置页 | ✅ |

### 6. 跨平台

- **用户端**：标准 Web 浏览器（桌面为主；移动非 Phase 1 目标）。
- **部署端**：静态 `dist/` 与 CPU 架构无关；镜像支持 `linux/amd64`（当前 VM）与后续 `linux/arm64`。
- **未来桌面（可选）**：同一 Web 产物可套 **Tauri** 等壳；Phase 1 不实施。

## 理由

- **Docker / VM 友好**：运行时无 Node，web 容器内存占用低，与「三服务拆分」一致。
- **与 gateway 咬合**：相对路径 `/api/v1` 使 web 零运行时 env，避免 CORS 与多环境配置漂移。
- **与契约层一致**：TS 类型从 `packages/contracts` 生成，契合 ADR-009、ADR-017。
- **满足产品 SLO**：React 生态足以承载 diff、流式 token、时间线；不必为 SSR 引入 Next.js 运行时。
- **跨平台**：Web 即最大公约数；静态产物易于多架构部署与未来桌面壳复用。

## 后果

### 正面

- web 镜像职责单一：仅静态资源 + nginx。
- 开发体验：`pnpm dev` 热更新；与 Python 服务依赖完全隔离。
- CI 可独立：`web` lint / typecheck / build 与 `api` / `runtime` 并行。

### 负面

- 需维护 Node 构建链（仅 CI 与 Dockerfile build stage）。
- 首屏加编辑器后 bundle 需 code-split 与懒加载治理。
- 若强需求 SSR/SEO，本决策需复审（当前产品无此需求）。

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| **Next.js（Node 运行时）** | SSR 非必需；增大镜像与 VM 内存；配置面复杂 |
| **Next.js 静态导出** | 可行但路由/App Router 约束多，不如 Vite 直接 |
| **Vue + Vite** | 同样可行；团队无历史包袱时 React 编辑器生态更成熟 |
| **Flutter Web** | 编辑器与 diff 生态弱；与现有 TS codegen 链路不匹配 |
| **Phase 0 永久纯 HTML** | 与 Phase 1 双场景工作台差距过大；仅作过渡可接受 |
| **web 容器内 `pnpm start` 常驻 Node** | 违背轻量部署；增加 healthcheck 与依赖攻击面 |

## 关联文档

- [`03-docker-runtime.md`](../03-docker-runtime.md) §5.4、§7.2
- [`04-development-standards.md`](../04-development-standards.md) §1、§2、§3.2
- [`08-event-projection-pipeline.md`](../08-event-projection-pipeline.md) §5
- [`09-product-modes.md`](../09-product-modes.md) §0、`web/scenarios/*`
- [`10-product-experience.md`](../10-product-experience.md) §5
- [ADR-001](001-three-service-split.md) — web 独立服务
- [ADR-004](004-sse-turn-streaming.md) — SSE 协议
- [ADR-009](009-protocol-four-layers.md) — Projection 消费、TS codegen
