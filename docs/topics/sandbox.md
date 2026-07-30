# 31 — Workspace 沙箱逃逸与防护

> **状态**：执行中（2026-07）— **E1–E3 + PR2 ✅**；E4 默认无网 ⏸；PR1/SW1/SB4/SB5/PR3 待续。  
> **本模块维护**：威胁枚举（SE）· 隔离加固（SB）· 密钥/出站脱敏加固（PR）· 敏感词钩子（SW，配置暂空）· **执行方案（§10）**。  
> **关联**：[03](../core/03-docker-runtime.md) §8（工作区/沙箱）· [06](../core/06-tools-and-context.md) · [13](../core/13-rate-redlines.md) R1–R5 · [27](multi-tenancy.md) · [21](../learn/agent-system-qa.md) Q11 · [32](../archive/32-execution-plane-and-local-runner.md)（可选本地执行面 · 待决）· 现有 `privacy/redact.py` · `privacy/secret_scan.py` · `tools/core/shell.py`。  
> **纪律**：不另开 `*-execution` 平行文；排期与 DoD 只维护在本文 §10。

---

## 0. 原则与边界

两条硬约束（与 [30](../archive/30-quality-and-agility.md) 同构；服从 [13](../core/13-rate-redlines.md)）：

1. **不影响 Agent 交互逻辑**：不改 `AgentEngine` while 语义、事件契约、审批门、Plan 相位、工具名/参数对外形状。加固落在 **exec 外围 OS 隔离**、**env/挂载/网络策略**、**工具 handler 内确定性门闩**；禁止为安全再加同步 LLM 裁判或固定 pipeline。
2. **不影响交互速率**：R1 不挡 `turn.accepted`；R2 首 token 前不加模型调用；R3 热路径同步 CPU 毫秒级；R4 重扫/审计异步；R5 可测才合并。隔离方案优先 **一次启动成本 / 每次 exec 固定开销可预算**，拒绝热路径重 tokenizer、CE、全量 AST。

**威胁模型（本文默认）**：

| 角色 | 假设 |
|------|------|
| 对抗模型 / prompt injection | 可任意选工具与参数；可诱导用户点 Approve |
| 合法用户误批 | 审批文案可能被忽略；不能只靠 UX |
| 运维面 | api 挂 `docker.sock` 等 **不在** agent 工具默认可达路径；但仍记为 Critical 旁路 |

**明确承诺与边界（现状 · 2026-07）**：

| 层 | 现状 |
|----|------|
| 文件工具 | `_resolve_path`：必须落在当前 Work 根内 |
| **exec OS 沙箱** | 镜像含 **bubblewrap** 且 PATH 可见时，`run_command` / `run_tests` 等经 `sandbox.py` **默认包裹**；可写面 ≈ work_root |
| 出网 | **默认保留**（批准后的 `curl` 可用）；护的是主机盘，不是禁业务上网 |
| 无 bwrap | 本机/缺包时降级为未包裹（`TOOL_SANDBOX=off` 仅排障）；嵌套 Docker 可能 weaker |
| 仍不承诺 | gVisor / 完整不可信代码多租户 OS 级隔离；PR1/SB4/SB5 等边角见 §10.8 |

> §0 旧句「不是 bubblewrap」已过时——E2 已落地。细节与威胁表见下文；面试口径见 [21](../learn/agent-system-qa.md) Q11。

**成熟方向优先序**（对齐 Claude Code / Codex 等：隔离 Bash，不改 Agent loop）：

```text
1. 收窄免审 exec 语义（run_tests argv 门闩）  ← ✅ E1
2. OS 级包一层 shell（bwrap 已落地；Landlock 可选演进）← ✅ E2
3. 网络与密钥隔离（默认无网 ⏸ 产品否决；env deny ✅；脱敏加厚待续）
4. 出站与落盘脱敏加厚（PR2 ✅；PR1/PR3 待续；敏感词钩子默认空）
5. 容器/compose 加固（SB5 待续）
```

**交互守线（执行时反复核对）**：

| 允许 | 禁止（会伤交互逻辑/速率） |
|------|---------------------------|
| 同一工具名/参数；同一审批事件 | 为安全新增同步 LLM / router / judge |
| `run_tests` 保持免审，但 **只准测试启动器** | 靠「去掉 never、多弹 Approve」当主修复（UX 变差） |
| 失败时返回明确 stderr / 既有 error 形 | 静默改 Plan waive、改 SSE 契约、改 while 语义 |
| 包装开销只在 tool 执行期 | 挡 `turn.accepted` / 首 token 前加调用 |

否决（与速率/交互冲突）：每 Turn 同步 LLM 安全评审 · 默认全命令 LLM 分类 · 热路径深度内容理解 ACL · 用审批次数堆安全（成熟产品用 **OS 沙箱换自主性**，不是用更多人工闸）。

---

## 1. 现状基线（诚实口径）

| 层 | 现状 | 结论 |
|----|------|------|
| 文件工具 `*_resolve_path` | `resolve()` + `relative_to(work_root)`；seed 写拒绝 | **结构化读写大致锁在 Work** |
| `run_command` / `run_tests` | 经 `sandbox.py`；有 **bwrap** 则默认 FS 沙箱 | **可写 ≈ work_root**；出网默认开；无 bwrap 时降级 |
| `run_tests` 门闩 | `test_command_gate` 启动器白名单；profile `never` 免审 | **不能免审任意 shell** |
| `read_lints` | 固定 `ruff`；可走 argv 入口 | 面窄 |
| 子 agent | 同进程 / 同 TenantContext；verify 含 `run_tests` | 继承同一沙箱入口 |
| 子进程 env | deny-by-default 允许集 | ✅ E3 基线 |
| 出站脱敏 | shell 出站 `redact_text`（PR2）；模式集可再扩（PR1） | 部分 ✅ |
| 写盘密钥扫描 | `secret_scan` 短预算；超时放行 + 异步重扫 | 已有 |
| runtime 容器 | 非 root `app`；镜像装 bubblewrap；无 privileged / 无 sock | **直接宿主机破出难** |
| api 容器 | 常 root + `docker.sock` + `/repo` | **运维 Critical 面**（非 agent 默认路径） |
| writing 场景 | 默认无 `run_command` / `run_tests` | **显著更安全**；仍非 gVisor |

---

## 2. 可能出现的问题（威胁枚举）

编号 **SE*** = Sandbox Escape / 控制失效面。严重度：对「workspace 承诺」或「密钥/租户隔离」的破坏程度。

### 2.1 路径与文件系统（文件工具面）

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-P1** | 相对路径穿越 | `../../../etc/passwd`、混用 `\` | 高（若未校验） | 文件工具：**已挡** |
| **SE-P2** | 绝对路径 | `/etc/shadow`、`/data/works/other` | 高 | 文件工具：**已挡** |
| **SE-P3** | 符号链接逃出 | workspace 内链到 `/etc` 或其它 Work | 高 | 文件工具：`resolve` 后 `relative_to` **已挡**；exec 有 bwrap 时写出界 **已挡** |
| **SE-P4** | TOCTOU / 竞态 | 校验后替换为 symlink | 中 | 文件工具窗口短；shell 无关 |
| **SE-P5** | 编码 / 空字节 / Unicode 规范化 | `%2e%2e`、异常 Unicode 同形 | 低–中 | Python `Path` 通常安全；仍须测 |
| **SE-P6** | seed 写穿 | 改 `sources/seed/**` | 中 | 工具断言 + RO 挂载 |
| **SE-P7** | 宿主机 bind 混淆代理 | 在 workspace 放指向敏感宿主机路径的 symlink，诱使宿主机 IDE/脚本跟随 | 中 | 工具不跟随出界；**宿主机工具可能跟** |

### 2.2 Shell：模拟、重定向、管道（exec 主战场）

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-S1** | 任意 shell 字符串 | `create_subprocess_shell`；无 argv 白名单 | **高** | 设计如此 |
| **SE-S2** | **模拟工具名绕过审批** | `run_tests(command="curl …")`；profile `never` | **高** | **已存在产品洞** |
| **SE-S3** | 重定向写出界 | `echo secret > /tmp/x`；`> /data/works/…` | **高** | cwd 无效 |
| **SE-S4** | 管道 / 进程替换 | `cat $(…)`；`bash <(curl …)` | **高** | 同 S1 |
| **SE-S5** | 这里文档 / 多行脚本 | `cat <<EOF … EOF` 写任意内容 | 高 | 同 S1 |
| **SE-S6** | 解释器内逃逸 | `python -c 'open("/data/…")'`；`node -e` | **高** | 同容器 FS |
| **SE-S7** | 超时 / cancel 竞态 | 杀进程组前已写出或已外发 | 中 | 有 timeout/cancel；非原子隔离 |
| **SE-S8** | 输出截断掩盖 | stdout 截 32k；恶意已在侧信道完成 | 中 | 截断是 UX，非安全边界 |
| **SE-S9** | `run_command_mode=simulate` 错觉 | 评测/CI simulate 与 live 行为差；误以为已隔离 | 低（工程） | 模式开关存在 |

### 2.3 操作系统目录与进程面

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-O1** | 读系统目录 | `ls /`、`cat /etc/passwd`、`/proc`、`/sys` | 高（信息） | shell 可读 |
| **SE-O2** | 父进程 environ 偷密钥 | 同 uid 读 `/proc/<runtime-pid>/environ` | **高** | `_safe_env` **不防** |
| **SE-O3** | `/proc/self/fd`、mem | 尝试读打开的 fd / 映射 | 中–高 | 视内核与权限 |
| **SE-O4** | 写 `/tmp`、`HOME`、缓存 | 持久化 payload；污染后续 Turn | 中 | `/tmp`、cwd 作 HOME 可写 |
| **SE-O5** | 信号 / 进程组 | 杀兄弟进程、干扰同容器其它 Turn | 中 | 同容器共享 PID 命名空间 |
| **SE-O6** | 内核/提权 | 脏牛类；依赖未打补丁镜像 | 低（概率）/高（若成功） | 非特权容器降低面 |

### 2.4 多租户与 `/data`

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-T1** | 跨 Work 文件读写 | shell 扫 `/data/works/*` | **高** | 文件工具按 Work；**shell 无** |
| **SE-T2** | 向量库 / memory / artifacts | 读 `/data/vectorstore`、`memory`、他人 artifacts | 高 | 共享 `agent_data` 卷 |
| **SE-T3** | 检索面绕过 | 不走 SQL deny，直接读源文件 | 高 | 与 [27](multi-tenancy.md) 路径沙箱假设冲突 |

### 2.5 网络与横向

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-N1** | 打 Postgres | 默认网 + 连接串（若泄漏）dump 全库 | **高** | 同 compose 网 |
| **SE-N2** | 打内部 api / runtime | 带 `INTERNAL_SERVICE_TOKEN`（若可得） | 高 | 视秘密是否泄漏 |
| **SE-N3** | 出网 exfil | `curl` 外发工具结果 / 密钥 | **高** | 无默认 egress deny |
| **SE-N4** | 云 metadata | `169.254.169.254` 等 | 高（云上） | 视部署 |
| **SE-N5** | SSRF 经工具 | 用户内容诱导请求内网 URL | 中–高 | 无工具级 URL 策略 |

### 2.6 Docker / 容器 / 宿主机

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-D1** | runtime → 宿主机 | privileged / docker.sock / 危险挂载 | Critical | runtime：**无 sock、非 privileged** → 难 |
| **SE-D2** | api docker.sock | 控 daemon → 任意容器/挂载宿主机 | **Critical** | **api 已挂 sock**（ops/CI）；须保证 agent 不可达 |
| **SE-D3** | 敏感 bind | `..:/repo`、`.env:ro` 在 api | 高（api 面） | 只读仍含源码与配置线索 |
| **SE-D4** | 共享 PID/IPC/NET | 同机其它容器若共享命名空间 | 中 | 默认不共享则低 |
| **SE-D5** | 卷权限 / SELinux `:z` | 标签过宽导致宿主机其它进程可写 | 低–中 | compose 使用 `:z` |
| **SE-D6** | 镜像供应链 | 依赖含后门；curl 预装扩大面 | 中 | 常规运维问题 |

### 2.7 审批、委派、场景差

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-A1** | 审批文案误导 | UI 暗示「仅 workspace」但 exec 是整容器 | 高（信任） | 文案/文档债 |
| **SE-A2** | Plan executing 写盘粘性 | 放行文件写；**文档已声明 shell 仍批** | 中 | 需守线，勿把 shell 划进 waive |
| **SE-A3** | delegate → verify/shell | 子 agent 带 `run_tests` / `run_command` | 高 | 继承 S2/S1 |
| **SE-A4** | writing → agent 工具漂移 | 错误把 exec 加进 writing profile | 高 | 配置纪律 |

### 2.8 数据泄漏（密钥 / PII / 日志）— 非「逃出目录」但同属控制失效

| ID | 问题 | 手法摘要 | 严重度 | 现状 |
|----|------|----------|--------|------|
| **SE-K1** | 密钥进模型上下文 | 工具读到 `.env` / 对话粘贴 | 高 | 出站 `redact` 部分覆盖 |
| **SE-K2** | 密钥进 SSE / 投影 / 日志 | stdout 含 token；structlog 字段 | 高 | 日志有 redact processor；SSE 须核对 |
| **SE-K3** | 密钥经 shell 落盘绕过 secret_scan | `curl … > out`；scan 只挂在 write_file/export | **高** | **缺口** |
| **SE-K4** | 扫描超时放行 | 大文件超 50ms 预算先写入 | 中 | 设计取舍（R3）；异步重扫 |
| **SE-K5** | 自定义敏感词未覆盖 | 业务专有词、内部代号 | 中 | **钩子可建，词表暂不设置**（见 §4.3） |

---

## 3. 优化方案（防护）

### 3.0 方案总表

| 票 | 主题 | 成熟手段 | 对交互逻辑 | 对速率 | 优先 |
|----|------|----------|------------|--------|------|
| **SB0** | 关闭 `run_tests` 免审任意 shell | profile / argv 门闩 | 无（仍可跑测试） | **零** | **P0** |
| **SB1** | Exec OS 沙箱 | Landlock 或 bubblewrap；RW 仅 work_root | 无（工具 API 不变） | 每次 exec +数–数十 ms（可预算） | **P0** |
| **SB2** | 密钥离开可窃 environ | 文件/FD 侧信道；`hidepid`；最小 env | 无 | 启动期 | **P0** |
| **SB3** | 网络默认拒绝 | 无网 / 内联 allowlist；禁 metadata | 无 | 无（策略） | **P1** |
| **SB4** | argv 执行优于 shell=True | 常用路径 `execve` 列表；复杂命令仍审批 | 无 | 略降解析成本 | **P1** |
| **SB5** | compose 加固 | cap_drop、read_only root、tmpfs、拆 sock 职责 | 无 | 无 | **P1** |
| **PR1** | 出站/日志脱敏加厚 | 扩高置信正则；复用现有路径 | 无 | R3 毫秒级 | **P1** |
| **PR2** | shell 输出与事件脱敏 | 对 stdout/stderr/command 出站前 redact | 无 | 截断前线性扫描 | **P1** |
| **PR3** | 写盘扫描与 shell 对齐 | 可选：沙箱外不可写则自然消失；或异步扫新文件 | 无 | 异步（R4） | **P2** |
| **SW1** | 敏感词配置钩子 | env/文件词表；**默认空** | 无 | 词表空≈零成本 | **P2**（词暂不设） |

下列分票说明「做什么 / 不做什么 / 验收」。

---

### 3.1 SB0 — 堵住 `run_tests` 模拟审批绕过（P0）

**问题**：SE-S2。工具名像「跑测试」，语义是任意 shell，且 agent 下 `requires_approval=False`。

**执行选定（守交互）**：**argv / 启动器白名单**，**保留** `run_tests: never`。

| 做法 | 是否采用 | 理由 |
|------|----------|------|
| 白名单：仅 `pytest` / `python -m pytest` / `npm test` / `npx vitest` / `go test` 等 | **采用** | 免审语义仍成立；恶意 `command` 确定性拒绝；**不增加 Approve** |
| 去掉 `never`、一律审批 | **不采用为主修复** | 安全但伤 UX；与 Claude Code「沙箱后提高自主」相反 |
| 非白名单字符串自动改走 `run_command`（需审批） | **可选降级** | 模型仍能跑自定义命令，只是回到既有审批路径 |

verify 子 agent：继续可调 `run_tests`，但受同一白名单约束。

**不做**：用 LLM 判断「是不是测试命令」（违 R2）。

**验收**：单测 — `run_tests(command="curl …")` / `python -c …` → 拒绝（明确 error）；`pytest -q` → 仍免审执行。

**速率**：零（字符串前缀/shlex 解析，微秒级）。

---

### 3.2 SB1 — Exec 外围 OS 沙箱（P0，主隔离）

**问题**：SE-S3–S6、SE-O1、SE-T1–T3 — 凡 shell 可达处。

**成熟做法**（按部署约束选）：

| 方案 | 成熟度 | 要点 | 注意 |
|------|--------|------|------|
| **Landlock**（Linux 5.13+） | 内核 LSM；Chrome 等在用 | 进程树限制可访问路径；RW 仅 `work_root`（+可选 `/tmp/tool-*`） | 需内核支持；实现薄 |
| **bubblewrap (bwrap)** | Flatpak 同系；广泛 | 新 mount ns；只绑 work_root；可 `--unshare-net` | 镜像多一二进制；每次 exec 包装 |
| **gVisor / Kata** | 强隔离 | 容器级 | 运维重；可作远期，不作第一刀 |
| firejail | 常见但策略复杂 | 备选 | 优先级低于 bwrap/Landlock |

**推荐第一刀**：在 `run_shell_command` **唯一入口**外包一层（`run_command` / `run_tests` / `read_lints` 全走它）：

- 可见：`work_root`（RW）、只读 `/usr` `/lib` 等运行测试所需最小集  
- 不可见或不写：`/data/works` 兄弟、runtime 源码、宿主机其它 bind  
- 可选同票启用 `--unshare-net` 或配合 SB3  

**交互逻辑**：工具名、参数、审批事件、SSE 形状不变；失败时返回与今日类似的 `PermissionError` / non-zero + stderr。

**速率**：包装开销应 **可度量**（目标：p99 额外 &lt; 50ms，或文档化 SLO）；禁止在包装路径上做内容 LLM。

**验收**：容器内用例 — `run_command` 批准后 `cat /etc/passwd` 或 `ls /data/works` 失败；`echo x > $WORK_ROOT/f` 成功；既有 agent golden 全绿。

---

### 3.3 SB2 — 密钥与敏感配置脱敏隔离（P0）

**问题**：SE-O2、SE-K*、SE-N1/N2。

**成熟做法**：

1. **运行时秘密不进长驻 environ**：`DATABASE_URL`、provider key、`INTERNAL_SERVICE_TOKEN` 等改为启动后读入内存/FD，或仅挂载在 **tool 子进程不可读** 的路径；工具包装后的进程 **无** 这些键。  
2. **加固现有 `_safe_env`**：默认 **deny-all + 显式 allow**（`PATH`、`LANG`、`HOME`、`PWD`、语言工具需要的少量变量），替代「复制再剥前缀」。  
3. **`hidepid=invisible`**（若编排允许）或独立 user ns，降低 `/proc` 窥探。  
4. **出站**：保持「正则脱敏、不用 LLM」（已有 A15 口径）；见 PR1/PR2。  
5. **落盘**：保持短预算 secret_scan（A16）；SB1 落地后 shell 写出界自然消失，PR3 作补。

**敏感词（业务）**：见 §4.3 — **只建钩子，不预置词表**。

**速率**：env 构造 O(键数量)；redact 保持预编译正则。

---

### 3.4 SB3 — 网络策略（P1）

**问题**：SE-N1–N5。

**成熟做法**：

- 默认：**tool 子进程无网**（bwrap `--unshare-net` 或独立 netns）。  
- 若必须装包/测集成：显式 **用户触发** 或 profile 开关「允许网络的 run_command」，默认关。  
- 容器层：egress 防火墙 / 无默认对外；阻断 link-local metadata。  
- Postgres：**不要**让 tool netns 解析到 DB；runtime 主进程保留连库能力。

**交互**：默认无网可能改变「agent 自己 curl 查文档」类行为 — 属 **能力收敛**，不是 loop 变更；须在 agent system 文案声明「无外网，用 workspace / 已索引 sources」。若产品坚持要外网，则 **仅审批后的 run_command** 进入「有网沙箱」变体，且仍无 DB 路由。

**速率**：无额外模型；策略零热路径成本。

---

### 3.5 SB4 — 少用 shell=True（P1）

**问题**：SE-S1、S4、S5。

**成熟做法**：对 `read_lints`、白名单测试启动器走 `create_subprocess_exec`；自由形态命令保留 shell 但必须审批 + SB1。  
对齐业界「structured tool args，少拼 shell」。

---

### 3.6 SB5 — Docker / Compose 加固（P1）

**问题**：SE-D1–D6。

| 项 | 做法 |
|----|------|
| runtime | `cap_drop: [ALL]`；按需 `cap_add`；`security_opt: [no-new-privileges]`；根 FS `read_only` + `tmpfs` |
| 秘密 | 不把 `.env` 挂进 **agent 可读** 树；api 的 sock **永不**挂到 runtime |
| sock | ops/CI 专用侧车或仅 api；网络策略禁止 runtime→docker API |
| 镜像 | 最小工具集；评估是否需预装 `curl` |
| 文档 | 03 §8.3 改为：「文件工具路径沙箱；exec 以 SB1 为准」 |

---

### 3.7 PR1 / PR2 / PR3 — 数据脱敏防护（密钥优先）

延续现有架构：**Guard = 出站 redact + 写盘 scan**；不加 LLM 脱敏。

| 票 | 做什么 | 不做 |
|----|--------|------|
| **PR1** | 扩高置信密钥形态（GitHub fine-grained、Slack、通用 `Bearer` 长 token 等）；保持预编译、可单测 | 不扫自然语言「像秘密」的猜测 |
| **PR2** | shell 结果进入模型 / 日志 /（若适用）投影前走同一 `redact_text`；`command` 字段同样处理 | 不在红线路径加模型摘要 |
| **PR3** | SB1 后界外写消失；可选 inotify/异步扫 work_root 新文件（R4） | 不在每次 keystroke 全库扫 |

**与密钥相关的分层**：

```text
生成/配置 → 加密落库（ADR-019）→ runtime 主进程可用
                ↓
         tool 子进程：不可见（SB2）
                ↓
         若仍进文本：出站 redact（PR1/2）
                ↓
         若要落盘：secret_scan（现有 + PR3）
```

---

## 4. 敏感词（SW）— 钩子先留，词表暂空

> 用户要求：**敏感词可人工配置；当前暂不设置具体词。**

### 4.1 目标

在 **不改交互逻辑、不伤速率** 的前提下，预留与密钥正则并列的 **可配置字面/词表匹配**（公司名、内部项目代号、客户专名等）。

### 4.2 建议形状（实现时）

| 项 | 建议 |
|----|------|
| 配置源 | env 路径如 `SENSITIVE_TERMS_FILE`；或 DB/设置页（后期） |
| 默认 | **空文件 / 未设置 = 禁用**（零成本） |
| 匹配 | 字面或简单规范化（大小写折叠）；预编译；超预算则跳过并指标（同 secret_scan） |
| 作用点 | 与 `redact_text` / `gate_write_content` **同一管道**；替换为 `[REDACTED_TERM]` |
| 禁止 | 空默认塞入产品词；禁止 LLM 扩词；禁止热路径加载远端词表 |

### 4.3 当前决议

- **SW1**：文档与设置键位预留；**不提交任何敏感词列表**。  
- 落地 PR 时仅加「空文件行为」单测，避免误伤写作/代码正文。

---

## 5. 落地顺序（摘要）

详细执行方案、切片、DoD、风险 → **§10**。

```text
E0  证明与口径（文档已部分完成）
E1  SB0  run_tests 启动器白名单（保 never）
E2  SB1  shell 唯一入口 OS 沙箱（Landlock → bwrap）
E3  SB2  deny-by-default env + 秘密隔离
E4  SB3  tool 默认无网（可与 E2 同 PR 若 bwrap）
E5  PR2 → PR1 → SW1 空钩子 → SB4/SB5 → PR3
```

---

## 6. 与速率红线对照（合并门）

| 红线 | 本模块如何满足 |
|------|----------------|
| R1 | 沙箱包装在 **tool 执行时**，不挡 `turn.accepted` |
| R2 | 无安全用途同步 LLM |
| R3 | redact/scan/词表：预编译 + 预算；超时跳过并指标 |
| R4 | 重扫、审计、词表热更新 → 异步 |
| R5 | SB0/SB1/SB2 无单测不合并；SB1 须有「界外失败」断言 |

**交互逻辑守线**：不改审批状态机事件名；不把 shell 划进 Plan executing 免批集合；不静默改 tool schema。

---

## 7. 验收场景（方案级，供将来开票）

| # | 场景 | 期望 |
|---|------|------|
| V1 | 文件工具 `read_file("/etc/passwd")` | 拒绝（已有） |
| V2 | 批准后 `run_command`：`cat /etc/passwd` 或 `ls /data/works` | SB1 后失败 |
| V3 | `run_tests(command="curl http://…")` | SB0 后需审批或拒绝 |
| V4 | 子进程 `environ` / `/proc` 窥父进程 | 不见 `DATABASE_` / provider key（SB2） |
| V5 | 写出含 `sk-…` 的文件经 write_file | secret_scan 挡（已有） |
| V6 | shell 重定向写密钥到 work_root 文件 | PR2/PR3 或事后异步告警；SB1 至少不能写到其它 Work |
| V7 | `SENSITIVE_TERMS_FILE` 空 | 行为与今日 redact 完全一致 |

---

## 8. 票状态

| 票 | 状态 |
|----|------|
| SE 威胁枚举（本文 §2） | ✅ 文档 |
| 执行方案（本文 §10） | ✅ 文档；E1–E4 + PR2(shell) 已实现 |
| SB0 / SB1 / SB2 / SB3 | ✅ 代码 |
| PR2（shell 出站 redact） | ✅ |
| PR1 / SW1 / SB4 / SB5 / PR3 | 📋 待续 |
| 敏感词词表 | ⏸ **故意不设置** |

落地后回写 §10.8 与 [docs/README.md](README.md) 实施状态；E2 已落地时可补 ADR「exec 必须经 OS 沙箱入口」。

---

## 9. 相关代码锚点（便于开票）

| 区域 | 路径 |
|------|------|
| 路径沙箱 | `services/runtime/app/tools/core/tools.py` → `_resolve_path` |
| Shell | `services/runtime/app/tools/core/shell.py` → `run_shell_command` / `_safe_env` |
| 审批覆盖 | `services/runtime/app/scenarios/profiles/agent.yaml` → `run_tests: never` |
| 注册 | `services/runtime/app/tools/bootstrap.py` |
| 出站脱敏 | `services/runtime/app/privacy/redact.py` |
| 写盘扫描 | `services/runtime/app/privacy/secret_scan.py` |
| 挂载 | `deploy/docker-compose.yml`（workspace、seed、api sock） |

---

## 10. 执行方案（开票用）

> **目标**：在 **不改 Agent 交互逻辑、不伤交互速率** 的前提下，把「workspace 承诺」从文件工具扩展到 exec。  
> **成熟对标**：Claude Code = **只沙箱 Bash**（Linux `bubblewrap` / macOS Seatbelt），Agent loop / 文件工具不变；OpenAI Codex = **Landlock + seccomp 默认开**。我们已在 Docker 内 → **优先 Landlock**（嵌套 bwrap 常需 weaker `/proc`，隔离变弱）。  
> **策略一句话**：**用 OS 边界换安全，用白名单保免审 UX**——不靠多弹审批，不靠 LLM 安检。

### 10.1 非目标（本执行方案明确不做）

| 不做 | 原因 |
|------|------|
| 改 `AgentEngine` / 事件 / Plan 相位 / 工具 JSON schema 名 | 伤交互逻辑 |
| 去掉 `run_tests: never` 当主修复 | 增加 Approve = UX 回退 |
| 同步 LLM 安全分类 / 默认 judge | 违 R2、伤速率 |
| 第一期上 gVisor / Kata | 运维重；Docker+Landlock 已够当前威胁模型 |
| 预置敏感词表 | 产品决议：钩子可建，词暂空 |
| 把 api `docker.sock` 当面立刻拆掉 | 属运维面；记入 E5，不挡 E1–E3 |

### 10.2 架构落点（唯一变更面）

```text
模型选工具（不变）
    → ToolExecutor 审批门（不变；SB0 不增加新门）
        → handler
            → run_shell_command   ←── 唯一加固点（SB1/SB2/SB3/SB4）
            → run_tests 白名单    ←── SB0（handler 入口）
            → write_file/_resolve_path  ←── 已有；不动语义
        → 出站 gateway redact     ←── PR1/PR2（已有管道加厚）
```

**原则**：所有 exec（含 `read_lints`）必须经 `run_shell_command`（或后续 `run_execve`）；禁止旁路 `create_subprocess_*`。

### 10.3 切片与 DoD

#### E1 — SB0 `run_tests` 启动器白名单（预计 0.5–1d）

| 项 | 内容 |
|----|------|
| **改哪里** | `tools/core/tools.py` → `run_tests`；可选小模块 `tools/core/test_command_gate.py`；更新 `bootstrap` 描述一句；**保留** `agent.yaml` 的 `run_tests: never` |
| **行为** | `shlex.split` 后 argv[0]（及 `python -m pytest` 形态）∈ 允许集才执行；否则返回 `status=rejected` / `error=test_command_not_allowed`，**不**升级为自动 `run_command`（避免模型困惑）；描述里写清：非常规测试请用需审批的 `run_command` |
| **允许集 v1** | `pytest`；`python`/`python3` + `-m` + `pytest`；`npm`/`pnpm`/`yarn` + `test`；`npx` + `vitest`/`jest`；`go` + `test`。flags 自由（仍在沙箱内） |
| **交互** | 合法 `pytest -q`：**仍免审、仍同路径**。非法 command：立即工具错误，不进审批、不挡其它工具 |
| **速率** | 微秒级解析；R1–R3 无影响 |
| **测试** | `tests/test_run_tests_gate.py`：允许/拒绝矩阵；`test_input_compiler` 仍断言 `run_tests` 免审 |
| **DoD** | 单测绿；`curl`/`bash -c`/`python -c` 无法经 `run_tests` 免审执行 |

#### E2 — SB1 Exec OS 沙箱（预计 2–3d，主收益）

| 项 | 内容 |
|----|------|
| **改哪里** | 新建 `tools/core/sandbox.py`；`shell.py` 的 `run_shell_command` 调用它；settings：`TOOL_SANDBOX=landlock\|bwrap\|off`（默认 **landlock**，CI/无内核能力时 **fail-open 仅 dev** / prod **fail-closed 可配**） |
| **策略选定** | **① Landlock**（Codex 同系）：限制 RW 路径 = `work_root` + 私有 `/tmp/tool-{turn}`；RO 需要时再开系统路径。**②** Landlock 不可用 → **bwrap**（Claude Code 同系），Docker 无特权嵌套时启用 weaker `/proc` 绑定并 **打指标警告**。**③** 皆不可用：`TOOL_SANDBOX=off` 仅本地；生产默认拒绝 exec 或降级为已审批+告警（产品二选一，**推荐生产 fail-closed**） |
| **交互** | 工具名/参数/审批不变；界外访问变为命令失败（stderr），模型按既有失败恢复即可 |
| **速率** | 目标：包装 p99 额外 **&lt; 20ms**（Landlock）/ **&lt; 50ms**（bwrap）；单测断言 mock 路径不测墙钟，另加可选 bench 指标 |
| **嵌套注意** | 我们跑在 Docker 内：优先 Landlock；文档写明 bwrap weaker 模式削弱 `/proc` 隐藏（对齐 Claude `enableWeakerNestedSandbox` 诚实口径） |
| **测试** | 集成：临时目录为 work_root 时，`echo a > $root/f` OK；`echo a > /tmp/out-of-policy` 或读 `/data/works` **失败**（在 sandbox 开时）；`TOOL_SANDBOX=off` 行为回归现网 |
| **DoD** | 所有 shell 入口经沙箱；V2 验收场景绿；agent golden 不挂；runtime Dockerfile 如需 `bubblewrap` 包则写入 [03](../core/03-docker-runtime.md) |

#### E3 — SB2 秘密与 env（预计 1d）

| 项 | 内容 |
|----|------|
| **改哪里** | `shell.py` → `_safe_env` 改为 **deny-by-default + allowlist**（`PATH`/`LANG`/`HOME`/`PWD`/`TERM`/`USER` + 显式 `TOOL_ENV_ALLOW`）；主进程密钥加载路径审计（能迁则迁出 environ） |
| **交互** | 无；测试若依赖某 env，用 allow 列表加项 |
| **速率** | 启动/每次 exec 复制小 dict |
| **测试** | 子进程 env 无 `DATABASE_`/`MODEL_`/`INTERNAL_`；若可测 `/proc` 则加（容器权限允许时） |
| **DoD** | V4；现有 simulate 模式单测仍绿 |

#### E4 — SB3 默认无网（预计 0.5–1d，可并进 E2）

| 项 | 内容 |
|----|------|
| **做法** | Landlock 不管网 → 配 **network namespace** 或 bwrap `--unshare-net`；settings `TOOL_NET=off\|allow`（默认 **off**） |
| **交互** | **能力收敛**：agent 不能随便 `curl` 外网——在 `agent/system.md` 加一句「工具默认无外网；资料用 workspace/sources」。**不改**审批状态机。需要联网的安装类命令：用户批准的 `run_command` + `TOOL_NET=allow` 会话开关（后期），第一期可只支持全局 env |
| **是否伤「交互逻辑」** | 属工具能力边界，与 Claude Code domain allowlist 同思路；**不是** loop 变更。若产品短期不能接受无网：E4 可延后，E2 仍先做 FS |
| **DoD** | 沙箱内 `curl 1.1.1.1` 失败；runtime→postgres 主进程仍通 |

#### E5 — 脱敏与纵深（按需，可并行小 PR）

| 顺序 | 票 | 要点 | 交互/速率 |
|------|-----|------|-----------|
| 1 | **PR2** | shell 的 stdout/stderr/command 进模型与日志前走 `redact_text` | 线性扫描；截断前做；R3 |
| 2 | **PR1** | 扩高置信密钥正则（精选，可单测） | 同左 |
| 3 | **SW1** | `SENSITIVE_TERMS_FILE`；**默认未设置=noop**；无词表提交 | 空=零成本 |
| 4 | **SB4** | `read_lints` / 白名单 `run_tests` → `create_subprocess_exec` | 略简 |
| 5 | **SB5** | runtime `cap_drop`/`no-new-privileges`；文档强调 sock 不进 runtime | 无 |
| 6 | **PR3** | 可选异步扫 work_root 新文件 | R4 |

### 10.4 建议 PR 切分（可审、可回滚）

| PR | 内容 | 合并门 |
|----|------|--------|
| **PR-A** | E1（SB0）+ 描述文案 | runtime 单测；不必全量 gate 若仅 runtime |
| **PR-B** | E2（SB1）核心 + 逃逸单测 + 03/31 状态回写 | `make runtime-test`；相关 golden |
| **PR-C** | E3（SB2）± E4（SB3） | 同上 + 无网用例（若含 E4） |
| **PR-D** | PR2 → PR1 → SW1 空钩子 | privacy 单测 |
| **PR-E** | SB4 + SB5（compose） | smoke |

每个 PR：**可独立回滚**；`TOOL_SANDBOX=off` 作紧急开关（仅非生产或明确 break-glass）。

### 10.5 证明命令（每切片）

```bash
# E1
cd services/runtime && python3 -m pytest tests/test_run_tests_gate.py tests/test_input_compiler.py -q

# E2+（落地后）
cd services/runtime && python3 -m pytest tests/test_shell.py tests/test_sandbox_escape.py -q

# 回归
make runtime-test
# 合并前
make gate
```

### 10.6 风险与缓解

| 风险 | 缓解 |
|------|------|
| Docker 内 Landlock/bwrap 不可用 | 探测 + 指标；生产 fail-closed；dev 可 off；文档写 nested 限制 |
| 无网导致「agent 爱 curl 查文档」变差 | system 文案引导 sources；需要时再开 allowlist（Claude 同模式） |
| 白名单过窄误伤 | 允许集可配置 `RUN_TESTS_ALLOWLIST`；误伤时扩列表，不开放任意 shell |
| 脱敏误伤代码里的示例 key | 仅高置信形态；超时跳过；单测夹具用假 key |
| 审批 UI 仍暗示「仅 workspace」 | 文案小改（非逻辑）：批准 shell 时提示「命令在工具沙箱内执行」 |

### 10.7 成功标准（执行完成时）

1. **交互**：合法 agent 路径（读 → 改 → `run_tests`/`read_lints` → 交付）步骤数与审批次数 **不劣于今日**（`run_tests` 仍免审）。  
2. **速率**：TTFB / 首 token 路径无新增同步；exec 包装开销在预算内。  
3. **安全**：V2/V3/V4 成立；`run_tests` 无法免审跑任意 shell；shell 默认写不出 work_root、默认看不见兄弟 Work。  
4. **文档**：§8 票状态回写 ✅；[03](../core/03-docker-runtime.md) §8.3 与实现一致。

### 10.8 票状态（执行跟踪）

| 切片 | 票 | 状态 |
|------|-----|------|
| E1 | SB0 | ✅ 已落地（启动器白名单 + argv exec；保留 `never`） |
| E2 | SB1 | ✅ 已落地（**Landlock → bwrap → off**；进程 sticky；见 `sandbox.py` / `landlock_fs.py`） |
| E3 | SB2 | ✅ 已落地（deny-by-default 固定允许集） |
| E4 | SB3 默认无网 | ⏸ **产品否决为默认**：护主机以 FS 为主；批准的 curl 外网应可用（见 Q11） |
| E5 | PR2 | ✅ 部分：shell stdout/stderr/command 出站前 `redact_text` |
| E5 | PR1 / SW1 / SB4 / SB5 / PR3 | 📋 待开工 |
| — | 敏感词词表 | ⏸ 不设置 |

**已落地锚点**：`tools/core/test_command_gate.py` · `tools/core/sandbox.py` · `tools/core/landlock_fs.py` · `tools/core/shell.py` · runtime Dockerfile(+retrieval) 安装 `bubblewrap` · 单测 `test_run_tests_gate.py` / `test_sandbox_escape.py`。

**默认即策略**：**Landlock → bwrap → off(degraded)**；首次 resolve **钉住**后端直至进程重启。Landlock：内核 ≥5.13 + LSM，RW 仅工作根（`preexec_fn`）；bwrap：userns 可用时挂载视图；皆不可用 → 诚实裸跑。**出网默认开**；固定 env 允许集。不向 `.env` / Settings 增加产品旋钮。仅排障可读 `TOOL_SANDBOX=off|landlock|bwrap`。  
**优化方案（降级 / userns / Landlock / 执行面）**：见 [36](../archive/36-sandbox-nested-exec-plan.md)（A+C ✅）。

**部署**：需重建 runtime 镜像后代码进容器（`make up-runtime` / 等价 rebuild）。Landlock 还依赖**宿主机内核**；4.18 等旧核上会跳过到 bwrap/off。
