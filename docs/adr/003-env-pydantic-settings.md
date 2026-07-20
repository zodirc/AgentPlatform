# ADR-003: 配置仅用环境变量 + 每服务 Pydantic Settings

## 状态

已接受（2025-06-30）

## 背景

`agent-langraph` 使用 800+ 行 `config.yaml`，叠加 `config.docker.yaml` 与 `.env` 双重 `${VAR:default}` 映射，导致：

- 本地、Docker、生产行为不一致
- Feature flag 与业务参数混杂，缺少 owner 与下线计划
- 新人无法判断「改哪个文件才生效」

新项目要求配置遵循 [十二要素应用](https://12factor.net/config) 原则。

## 决策

1. **禁止**在容器内通过 `CONFIG_PATH` 指向巨型 YAML 作为主配置源。
2. 每个服务（`api`、`runtime`）维护独立的 `app/settings.py`，基于 **Pydantic v2 `BaseSettings`** 读取环境变量，启动时校验。
3. 配置入口唯一：**`.env` → docker compose `environment` → 各服务 Settings**。
4. `.env.example` 只列 **Bootstrap 起栈变量**；高级旋钮以代码默认值为准，文档见 [`03` 附录 A](../03-docker-runtime.md)。`.env` 不入库；敏感项禁止在代码库中设生产默认值。
5. Feature flag 命名：`FEATURE_<NAME>_ENABLED`，必须关联 ADR 或 issue，新能力默认 `false` 且不影响 Phase 0 启动。
6. `api` 与 `runtime` 可共享连接类变量（如 `DATABASE_URL`），但**禁止**共享 Python 配置对象或跨服务 import Settings。
7. **运营配置**（模型供应商、API key 等高频变更项）存 PostgreSQL，经 Web 管理面热生效，**不**扩写 `.env` 为多份密钥堆叠；见 [ADR-019](019-model-provider-runtime-config.md)。`.env` 中 `MODEL_*` 仅作 Bootstrap **fallback**。

## 理由

- 环境差异只通过环境变量注入，与 Docker / K8s 部署模型一致
- Pydantic 启动校验可尽早暴露配置错误，缩短排障时间
- 每服务独立 Settings 防止配置耦合与隐式依赖
- 与 ADR-001 三服务拆分、独立镜像构建策略一致

## 后果

### 正面

- `docs/03-docker-runtime.md` 可作为配置唯一真相来源
- CI 与本地可通过同一 `.env.example` 模板对齐
- 配置变更可审计（env 清单 vs 代码中的 Settings 字段）

### 负面

- 复杂嵌套配置不如 YAML 直观（可用 JSON 字符串或分层 env 前缀缓解）
- 大量 flag 仍需治理，避免重新膨胀为「环境变量版 800 行配置」

## 备选方案

| 方案 | 否决原因 |
|------|----------|
| 保留主 YAML + env 覆盖 | 重复 agent-langraph 技术债 |
| 根目录单一 Settings | 违反服务边界，导致 api/runtime 配置耦合 |
| Consul / etcd 动态配置 | Phase 0–2 过度设计 |
| 编译进镜像的 config 文件 | 违反十二要素，环境切换需重建镜像 |
| 运营配置（模型 key）仅放 `.env` | 高频切换需重启；见 ADR-019 分层 |
