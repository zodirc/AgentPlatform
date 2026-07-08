# ADR-001: API / Runtime / Web 三服务拆分

## 状态

已接受（2025-06-30）

## 背景

`agent-langraph` 在单 FastAPI 进程中合并了 HTTP API、LangGraph 执行、静态 Web、调度器与多种引导逻辑。导致启动时间长、故障域大、无法对执行面独立扩缩。

## 决策

将系统拆为三个应用容器：

1. **api** — 控制面 HTTP：鉴权、会话、任务提交、SSE 代理
2. **runtime** — 执行面：LangGraph、LLM、检索、工具
3. **web** — 静态前端

另加 **gateway**（Caddy）作 TLS 与路由，**postgres** 作持久化。

## 理由

- 执行面可水平扩展（多 runtime 副本），控制面保持轻量
- api 镜像不含 torch/embedding，构建与部署更快
- 启动失败可定位到具体服务
- 与十二要素配置、内部 API 鉴权模型一致

## 后果

### 正面

- 清晰的团队分工边界（平台 API vs 运行时）
- 更小的攻击面（runtime 不暴露公网）

### 负面

- api ↔ runtime 多一次网络 hop（内网可接受）
- 需要维护内部 API 契约与 `INTERNAL_SERVICE_TOKEN`
- 本地调试需 compose 或多终端

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 维持单体 | 重复已有技术债 |
| api + worker 仅两分裂 | Web 与 API 仍耦合，静态资源与 API 发布节奏不同 |
| 微服务细分为 10+ 服务 | Phase 0 过度设计 |
