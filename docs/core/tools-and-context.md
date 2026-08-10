# 工具与上下文

工具协议、组窗压缩阶梯、exec 沙箱。两张图分别画 `_build_envelope` 与 bwrap 路径。

## 图

1. [组窗详流](../assets/context/context-assemble-ladder-zh.png) — 卫生 → fill 阶梯 → 模型  
2. [bwrap exec](../assets/sandbox/bwrap-exec-flow-zh.png) — `run_command` / `run_tests` · Landlock 正交  

![ContextEngine 组窗](../assets/context/context-assemble-ladder-zh.png)

![bwrap exec](../assets/sandbox/bwrap-exec-flow-zh.png)

## 1. 能力即工具

检索、改稿、exec、委派、验证都是 **工具**，由模型在 AgentEngine 循环内按需调用。  
加能力 = 注册 `ToolSpec` + handler，**不改 while、不加固定 pipeline 节点**。

典型字段：

| 字段 | 作用 |
|------|------|
| `name` / `description` / `input_schema` | 进请求级 `tools[]`（与 system 文本分离，利于 cache） |
| `side_effect` | 只读 / 写盘 / shell … 决定并行与审批默认 |
| `approval` | 是否打断等待用户 |
| `timeout_s` | 单次调用上限 |
| `handler` | async；可流式打事件 |

约束：

- 工具结果进窗前统一过 **budget**（超长截断并留再读指针）。  
- 只读可并行；写盘 / shell 默认审批更严。  
- RAG **只**以 `search_sources`（及同类）的 `tool_result` 回灌，禁止每轮预注入向量包。  
- 多 agent **只**经 `delegate` 子 Run，摘要回灌；禁止 supervisor 大图节点。

## 2. 请求通道怎么拼

与工作台 Usage 同名，但是 **材料清单**（不是又一张卡片海报）：

| 通道 | 内容 | 注意 |
|------|------|------|
| System | `scenarios/*/system.md` | 跨 step 求字节稳定；**不焊**工具 schema / 大纲全文 |
| Tools | `tools[]` how-to + schema | 与 system 文本分离；禁用工具用独立柜，不靠改长 system |
| Rules | `AGENT.md` / `outline.md` 等 ≈2k | 不焊进 system.md |
| Writing / Runtime / Session | 焦点、计划、步进注入 | Runtime 宜在 Conversation 之后 |
| Conversation | user / assistant / tool_results / compact | **卫生与 80/90/95 主要作用于此** |

物化顺序口诀：**稳定前缀 → 历史 → 易变垫底**  
`[system] → [rules] → [writing ctx] → [conversation…] → [runtime]`；`tools[]` 不进 message 串。

## 3. ContextEngine 逐步经过

每次准备调模型前跑 `ContextEngine._build_envelope`（代码：`context/engine.py` · `policy.py`）。

### 3.1 卫生（几乎每步，不看 fill）

| 步骤 | 做什么 |
|------|--------|
| **budget** | 单条超长 `tool_result` 截到约 **4k 字符**，留再读指针 |
| **read_fold** | 同一 path 的旧 `read_file` 正文去掉，只留最近一次 |
| **microcompact** | 历史里成串旧 tool 结果折成短占位；**不拆**当前配对 |

口诀：微折叠是卫生，**不是**超限压缩。

### 3.2 填充率

```text
fill_ratio ≈ 本窗估计 token / (context_window_tokens − output_reserve_tokens)
```

### 3.3 超限阶梯（只看阈值）

| 阈值 | 动作 | 损失形态 |
|------|------|----------|
| ≥ **0.80** | **collapse** | 留 head（意图）+ 热尾（`hot_zone_ratio≈0.35`）；中间 → `[collapsed…]` |
| ≥ **0.90** | **snip** | 删最旧**完整消息组**；可循环直到 fill&lt;0.90 或无可删 |
| ≥ **0.95** | **autocompact** | 整窗 → 一条结构化摘要；默认**确定性增量**合并；原件另仓可审计 |

摘要是最后一档，**不是每轮税**；也不是等到 100% 才做。

### 3.4 输出与旁路

- 得到 `ContextEnvelope`：压缩后 messages + `compaction_trace` + 用量 → `ModelGateway.stream`。  
- **只改本步模型窗**；不删磁盘草稿 / revisions；Web 聊天记录通常仍完整。  
- Turn 结束后若 fill ≳ **0.78**：可异步刷新 `sessions.context_summary`（软预压缩缓存），**不挡**本轮首 token；硬阈值来时优先吃缓存，而不是热路径同步再调一次摘要模型。

## 4. exec 沙箱（bwrap · 与审批正交）

```text
审批已过（或本工具免审）
  → run_command / run_tests handler
  → （可选）Landlock：进程能力收紧（内核支持时）
  → wrap_argv → resolve backend
       ├─ bwrap 可用 → 组 RO/RW/tmpfs argv → 子进程
       └─ 否则 → 直接 exec（无沙箱降级；日志可察）
```

bwrap 典型形态：

| 项 | 做法 |
|----|------|
| RO bind | 系统工具路径（如 `/usr` 下必要树） |
| RW bind | `{work_root} → /work` |
| tmpfs | `/tmp`、约定数据位 |
| chdir | `/work` |
| 网络 | 默认策略以实现为准；**沙箱主责是文件系统隔离，不自动等于断网** |

正交关系（审批图里也画了，无需另找独立对比图）：

| 门 | 问题 | 失败形态 |
|----|------|----------|
| **审批** | 用户允不允许跑这次工具 | `waiting_approval` / deny `tool_result` |
| **Landlock / bwrap** | 跑起来能碰哪 | 沙箱内 EACCES / 降级直 exec |

嵌套 Docker / 无 bwrap 包时的降级与威胁面，以本图 + runtime `tools/core/sandbox.py` 为准；不在热路径上再套一层 LLM 安全裁判。
