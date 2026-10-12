# 编码场景优化设计

> 对象：`agent` Profile 的编码链路（导览页 `docs/tour/pages/coding-fuse.html`）。
> 参照：Cursor Agent、Claude Code、OpenAI Codex（CLI / Cloud）公开可见的做法。
> 冲突：代码与契约 > 本文。本文引用的行为都已在当前代码中核对过，引用处给出文件路径。

---

## 0. 结论摘要

现链路的骨架是对的：符号表加 LSP 确认的 Locate，唯一 span 编辑，语法门，增量诊断，sandbox 执行，终局边 verify receipt，checkpoint 恢复义务。这几项在三家里都能找到对应物，有些做得比它们更严（例如“只有 LSP 确认过的位置才进 `definitions[]`”）。

主要问题不在骨架，而在四个层面：

1. **正确性缺陷**（P0，应当马上修）。编辑会改写 CRLF 和非 UTF-8 字节；编辑成功后模型无法再读该文件；`edit_file` 绕过秘密扫描；`.git/` 可被直接写；“快照可回退”没有任何消费方，且只保留最近一次前像。
2. **Python 单语言假设**。LSP、诊断、相关测试、`is_testish_command`、verify 门全部只认 Python。改 `.ts` / `.go` 文件时 `verify_pending` 根本不会置位，等于整条“改完再验”对非 Python 仓库失效。
3. **编辑原语与执行原语偏窄**。只有单 span 精确匹配；测试墙钟 60 秒且不可调；没有后台进程；没有多文件补丁。三家都在这些点上给了更宽的通道。
4. **验证闭环靠“催”，缺“透明”**。receipt 发出后实际再跑测试仅 0.25，相关测试采用率 0.0。继续加强文案收益有限。应当一边把验证成本降到接近零（自动 lint 回灌、产品模式可选的编辑后钩子），一边在 Turn 终态把“未验证”如实标给用户。

路线图见第 13 节：P0 为一组小而确定的修复，P1 为多语言与编辑/执行原语，P2 为回退、转向、审阅等产品能力。

---

## 1. 现状速览

```
用户消息 / problem.md
   │
   ▼
search_codebase（is_symbol_query 判定）
   ├─ 符号形 → 符号表 top5 候选 → LSP 在标识符列确认 → definitions[]
   └─ 非符号 → 转义后子串匹配 → hits[]（locate_incomplete=false）
   │
   ▼
read_file（read_registry：完整读过同一路径 → 硬拒）
   │
   ▼
edit_file（old_text 恰好 1 次 → 语法门 → 写前诊断基线 → 写盘
           → impact 引用 → 写后诊断 diff → related_tests）
   │
   ▼
run_tests / run_command（sandbox：plane HTTP → Landlock / bwrap；不可用则拒）
   │
   ▼
终局边：verify_pending ∧ 剩余步数 ≥ 10 → 注入 receipt → continue
```

关键实现：`tools/core/edit_tools.py`、`engine/verify_receipt.py`、`engine/read_registry.py`、`structural/providers.py`、`structural/test_summary.py`、`policy/snapshot.py`、`policy/plane.py`、`scenarios/agent/system.md`、`scenarios/profiles/agent.yaml`（均在 `services/runtime/app/` 下）。

---

## 2. 三家参照：值得借的点

只列与本链路直接相关、且公开资料能确认的做法。

| 维度 | Cursor | Claude Code | Codex |
|---|---|---|---|
| 定位 | 语义索引（embedding）+ grep + 文件搜索 | 不建向量索引，靠 grep / glob / read 的 agentic search | shell 里的 `rg` 为主 |
| 编辑 | search-replace 与 apply 模型；编辑后自动拉 lint 并回灌 | `Edit`（唯一匹配，可 `replace_all`）；要求先 Read，读后文件被改则拒写 | `apply_patch` 自由格式补丁：多文件、增删改、基于上下文的 hunk |
| 编辑后反馈 | lint 自动回灌，限次自修 | PostToolUse 钩子（格式化、lint、测试由用户配置） | 模型自行跑命令 |
| 执行 | 终端；可配置自动运行白名单 | Bash：可调超时、后台进程、读后台输出 | sandbox 模式（只读 / 工作区可写 / 全权）× 审批策略（含“失败后申请提权重跑”）；工作区可写模式默认断网 |
| 项目规则 | `.cursor/rules`（按 glob 生效）+ `AGENTS.md` | 分层 `CLAUDE.md`（用户 / 项目 / 子目录） | 分层 `AGENTS.md`（根到 cwd 逐级合并，有字节上限） |
| 回退 | checkpoint：每次改动前快照，一键恢复 | checkpoint / rewind：回到某条消息之前的代码与对话 | git 工作树；Cloud 任务产出 diff / PR |
| 计划 | todo 清单 | TodoWrite；plan mode（只读规划，批准后执行） | `update_plan` |
| 多代理 | 并行 agent（各自 worktree）、后台 agent | 子代理（独立上下文） | Cloud 并行任务 |
| 中途干预 | 运行中可追加消息 | 运行中可插话，下一步生效 | 运行中可追加消息 |
| 审阅 | Bugbot 审 diff | 子代理或命令审 diff | Cloud 的 code review |

三家共同的取舍：

- **编辑工具宽容、反馈即时**。匹配失败给可操作的错误；编辑后马上能看到改后的样子与诊断。
- **执行边界放在 sandbox，不放在命令白名单**。白名单只是用户体验，安全靠隔离。
- **回退是一等能力**。用户敢放手让 agent 改，是因为随时能撤。
- **项目规则可分层、按路径生效**，不是一段 2000 字的全局前缀。

---

## 3. 设计原则（沿用并补充）

沿用仓库已有原则：

- 捷径在 handler 内改道，工具名不变，保护前缀缓存。
- 评测下平台不代跑测试，官方分只看 harness。
- 义务只由工具事实驱动，不解析终稿自然语言；义务绑定最近一次编辑。

本文新增：

- **P-1 不改用户字节之外的字节。** 编辑只改 `old_text` 那一段；换行符、编码、BOM、权限、尾部换行一律保持原样。
- **P-2 模型看到的文件状态必须是当前状态。** 任何写盘（自己的编辑、shell 命令、外部修改）之后，模型都要能拿到新内容，或被明确告知已过期。
- **P-3 产品模式与评测模式分开开关。** 产品模式可以让平台替用户跑 lint 或测试，评测模式不行。两者共用一套代码，由 `ops_eval` 判定。
- **P-4 语言无关是默认，Python 是特例。** 任何“代码文件”判定、testish 判定、相关测试，都走语言注册表，不写死扩展名。
- **P-5 未完成要说出来。** 平台无法强迫模型验证时，至少把“未验证”如实写进 Turn 终态，交给用户判断。

---

## 4. 第一层：正确性缺陷（P0）

这些是行为错误，不是改进项。

### 4.1 编辑会改写换行符与非 UTF-8 字节

`edit_file` 读写用的是：

```python
text = target.read_text(encoding="utf-8", errors="replace")
...
target.write_text(updated, encoding="utf-8")
```

后果：

- `read_text` 默认做通用换行转换，CRLF 文件读进来变成 LF，写回仍是 LF。Windows 仓库里改一行，diff 是整文件。
- `errors="replace"` 把非法字节替换成 U+FFFD 再写回，Latin-1 / GBK 文件会被静默破坏。
- UTF-8 BOM 被保留为 `\ufeff` 字符，这一项尚可，但不受控。

方案：

- 以 `bytes` 读取，探测编码（UTF-8 → UTF-8-BOM → 声明编码 → 拒绝），探测换行风格（多数派）。
- 在 LF 归一化后的文本上匹配 `old_text`（模型几乎总是给 LF），替换后按原换行风格与原编码写回。
- 无法无损往返（解码再编码 ≠ 原字节）时拒写，返回 `error: "unsupported_encoding"`，不再静默替换。
- `write_file` 覆盖已有文件时同样继承原换行风格（除非新内容本身含 CRLF）。

验收：CRLF、GBK、带 BOM、无尾换行四类文件各编辑一次，`git diff` 只出现目标行。

### 4.2 编辑成功后模型读不到改后的文件

`read_registry` 在完整读过某路径后，后续 `read_file` 一律硬拒（`read_after_complete`）。唯一的放行口是编辑**失败**（`note_edit_failure_allows_reread`）。编辑**成功**、`run_command` 改写了文件（格式化、代码生成、`git checkout`），都不会让这条记录失效。

后果：连改三处之后，模型脑中的文件版本与磁盘不一致，只能凭记忆拼 `old_text`。这与 Claude Code 的做法方向相反：后者要求“改前先读”，并在“读后文件被外部改过”时拒写。

方案：把 registry 从“读过没有”改成“读到的是哪个版本”。

- `PathReadState` 增加 `content_hash`（或 `mtime_ns + size`）。
- `read_file` 的拒绝条件改为：完整读过 **且** 当前磁盘哈希等于读时哈希。哈希变了就放行，并在结果里标 `changed_since_last_read=true`。
- 自己的 `edit_file` 成功后，用写后内容更新哈希，这样不会因为自己的编辑放开重读；同时编辑结果附带写后片段（见 5.4），模型不需要重读。
- `run_command` / `run_tests` 结束后，对 registry 里的路径做一次批量 stat（廉价），变化的路径标为过期。

这同时修好了 P-2 的另一半：外部并发修改。

### 4.3 外部并发修改没有检测

用户在 IDE 里同时改同一文件时，`edit_file` 直接在最新磁盘内容上做替换。若 `old_text` 恰好仍唯一，用户的修改会被保留；若用户改的就是那一段，编辑报“未找到”，尚可。但 `write_file` 覆盖时会直接吞掉用户修改。

方案：复用 4.2 的哈希。`write_file` 覆盖已有文件时，若该路径在 registry 中有哈希且与磁盘不一致，返回 `error: "file_changed_since_read"`，附 diff 摘要，要求重读。`edit_file` 只在 `old_text` 匹配失败时附带“文件自上次读取后已变化”的提示。

### 4.4 `edit_file` 绕过秘密扫描

`write_file` 调用了 `gate_write_content`，`edit_file` 没有。模型完全可以用 `edit_file` 把密钥写进已有文件。

方案：`edit_file` 对 `new_text` 调用同一个 `gate_write_content`，只扫新增部分。

### 4.5 `.git/` 及其它元数据目录可写

`_resolve_path` 只拦工作区外与 seed 语料。`edit_file(".git/config", ...)` 或 `write_file(".git/hooks/pre-commit", ...)` 可以通过。后者等于在用户下次 commit 时执行任意代码，是经典的提示注入落点。

方案：写类工具拒绝 `.git/**`；`.github/workflows/**`、`.husky/**`、`.vscode/tasks.json` 这类“会被别的系统执行”的路径归入需审批类（即便本 Turn 已有 `writes_preapproved`）。

### 4.6 “快照可回退”名实不符

`policy/snapshot.py` 在写前保存前像到 `state.s1_snapshots`，审批矩阵据此放行写盘（“可回退，所以免审”）。但：

- 全仓没有读取 `s1_snapshots` 用于恢复的代码，用户与模型都没有回退入口。
- `snaps[path] = stored` 每次覆盖，同一路径第二次写之后，回不到 Turn 开始时的状态。
- 快照存在 TurnState 里，跟 checkpoint 序列化，大文件会撑大 checkpoint。

这条既是缺陷（免审的前提不成立），也是产品缺口。短期修法：只在首次写某路径时保存前像（`setdefault`），保证能回到 Turn 起点。完整回退设计见第 11.1 节。

### 4.7 生产 Profile 暴露测试桩

`agent.yaml` 的 `tool_names` 包含 `slow_tool`（`model/gateway.py` 中的 8 秒桩工具）。它的 schema 每步都进 `tools[]`，占 token 并可能被误调。应移到测试专用 Profile。

---

## 5. 第二层：编辑原语

### 5.1 同文件多处、原子

现状：一次 `edit_file` 只能改一处。改函数签名加三个调用点，需要四次调用，每次都跑完整的“写前诊断 → 写 → 引用 → 写后诊断 → 相关测试”，中间状态可能语法不通（语法门会拒掉其中某些中间步骤，迫使模型调整顺序）。

方案：`edit_file` 增加可选 `edits: [{old_text, new_text, replace_all?}]`。

- 所有 span 在原文上定位，要求互不重叠，然后一次性应用。
- 语法门、诊断、引用、相关测试只在最终结果上跑一次。
- 任一 span 失败则整体不写，返回每个 span 的状态。
- 保留单 span 的 `old_text/new_text` 形式，向后兼容。

`replace_all`：重命名局部变量这类场景直接给出，避免模型为每处出现拼唯一上下文。

### 5.2 多文件补丁

是否引入 Codex 风格的 `apply_patch`：

- 好处：跨文件改动一次提交，便于审批（一张 diff）和原子回退；对用该格式训练过的模型命中率高。
- 代价：新增工具名（一次性打掉前缀缓存），模型侧要多学一种格式。

建议：P2 再做，且以 Profile 开关控制，按模型选择暴露 `edit_file(edits[])` 还是 `apply_patch`，而不是两者同时暴露。`patch_tools.py` 已有 `git apply --check` 预检，可以作为实现基础。

### 5.3 匹配阶梯

现状只有精确子串计数。三家里匹配失败最常见的原因是空白：尾随空格、Tab 与空格混用、模型把缩进少写一级。

方案：按顺序尝试，命中即止，且每一级都要求**唯一**：

1. 精确匹配。
2. 换行归一（4.1 之后自然满足）。
3. 每行去尾随空白后匹配。
4. 每行去公共前导缩进后匹配，替换时把 `new_text` 重新缩进到原位置的缩进。

结果里写 `match_mode: exact | trailing_ws | reindent`。第 3、4 级在评测中单独统计，若发现误改再收紧。不做模糊相似度匹配：那会把“改错地方”变成静默行为。

### 5.4 编辑结果附写后片段

现状：成功结果只回 `old_text/new_text` 和摘要。模型不知道改后文件里那一段及其上下文到底长什么样，也不知道行号。

方案：结果附 `post_edit_excerpt`：改动区域前后各 5 行，带行号。配合 4.2，模型在大多数情况下不需要重读整个文件，也能把下一个 `old_text` 拼对。

### 5.5 编辑延迟

现状一次成功编辑串行执行：写前诊断（ruff + LSP，预算 30 秒）→ 写 → 引用（15 秒）→ 写后诊断（30 秒）→ 相关测试扫描（最多 650 毫秒）。最坏情况一次编辑约 75 秒，常见也要数秒；ruff 每次都起子进程。

方案：

- **写前基线缓存**：按 `(path, content_hash)` 缓存诊断结果。`read_file` 后台预取一次；连续编辑同一文件时，上一次的写后诊断就是下一次的写前基线，不需要再跑。
- **写后三件事并行**：引用、写后诊断、相关测试彼此独立，用 `asyncio.gather`。
- **引用改为按需**：编辑结果只附引用计数与前 5 处；完整列表由 `find_references` 获取。改的是函数体而不是签名时（可以用 AST 判断签名是否变化），跳过引用查询。
- **ruff 常驻**：用 `ruff server` 或批量调用，避免每次冷启动。

验收：同文件连续 5 次编辑的 p50 工具耗时下降一半以上。

---

## 6. 第三层：定位与理解

### 6.1 多语言

现状：`providers.py` 只有 pyright / jedi，`language_for_path` 只认 `.py/.pyi`。连带影响：

| 环节 | 对非 Python 文件的行为 |
|---|---|
| 符号表与 LSP 确认 | 不可用，定义查找退回文本 |
| `edit_file` 的 impact / checks | `non_code_path`，跳过 |
| verify 门 | `non_code_path` 不置 `verify_pending`，**收据永不发** |
| `related_tests` | 只生成 `python -m pytest` |
| `is_testish_command` | 不认 `npm test`、`vitest`、`go test`、`cargo test` |

方案：

- 建 `LanguageSpec` 注册表：扩展名 → 语言 id → LSP 启动命令 → linter → 测试文件命名规则 → 测试命令模板 → testish 正则。
- 首批：TypeScript/JavaScript（typescript-language-server、eslint、vitest/jest）、Go（gopls、`go vet`、`go test ./pkg/...`）、Rust（rust-analyzer、`cargo check`、`cargo test`）。
- “是不是代码文件”与“有没有 LSP”拆开：没有 LSP 的代码文件仍要置 `verify_pending`，只是 impact / checks 标为 `unavailable`。这一条单独就能修好非 Python 仓库的 verify 门，应作为 P0。
- 符号表的解析换成 tree-sitter（多语言一套代码），LSP 只做确认与引用。

### 6.2 自然语言查询

现状：含空白的查询走“转义后子串匹配”。“重试逻辑在哪”“鉴权中间件”这类问题几乎不会有子串命中。

三家两条路线：Cursor 建语义索引；Claude Code 明确不建，靠模型多轮 grep。本仓库 RAG 已经有向量检索能力，但编码场景刻意不接。

建议走中间路线，按收益分步：

1. **词法升级**（P1）：把自然语言查询拆成词，对标识符做驼峰与下划线切分后建倒排，按 BM25 排序，返回文件和符号级命中。成本低，没有新依赖。
2. **仓库地图**（P1）：按需返回目录树加每个文件的顶层符号签名，有预算上限（参考 Aider 的 repo map）。用于大仓库冷启动，替代被禁止的 `list_dir(".")` 漫游。
3. **语义索引**（P2，视评测而定）：符号级 chunk（函数 / 类）做 embedding，复用 sources-retrieval 平面。只有当 1、2 在“功能新增类任务”上明显不足时才做。

### 6.3 grep 改道丢失词面命中

现状：符号形 pattern 的 `grep` 整条改走定义查找。但模型 grep 一个符号，常常是想找**所有用法**，不是定义。改道后它只拿到定义。

方案：改道后的结果同时返回 `definitions[]`（LSP 确认）和 `hits[]`（词面，标 `lexical=true`，上限 50），二者分栏。保持“词面命中不进 `definitions[]`”的原则不变。

### 6.4 同名候选排序

符号表一次最多 5 个同名候选，LSP 按顺序确认，停在第一个成功的。大仓库里 `get`、`run`、`Config` 之类会挤掉真正的目标。

方案：候选按与“本 Turn 已读 / 已改文件”的路径距离、import 关系、是否测试文件排序；查询支持 `path_hint`；`pkg.Class.method` 点分形式用前缀收窄。

---

## 7. 第四层：执行与验证

### 7.1 测试运行器与 testish 判定

现状：`run_tests` 只接受 pytest 与 npm / pnpm / yarn test、vitest、jest；`is_testish_command` 只认 Python 系。于是 `run_command("go test ./...")` 不清 `verify_pending`，`run_command("npx vitest")` 也不清。

方案：

- `run_tests` 白名单与 testish 正则都从 `LanguageSpec` 生成。
- 允许项目在 `AGENTS.md` 或 `.agent/config.toml` 里声明测试命令（如 `make test`、`uv run pytest`、`tox -e py311`），声明过的命令视为 testish。
- `run_tests` 可接受 `cwd` 子目录参数（monorepo）。

### 7.2 超时与后台进程

现状：`tool_default_timeout_seconds = 60`，模型无法调整。中型项目的测试套件、`npm install`、`cargo build` 常常超过 60 秒，超时后模型只看到 `status=timeout`，往往重试同一条命令。

方案：

- `run_command` / `run_tests` 增加 `timeout_s` 参数，默认 120，上限 600；评测模式上限按题目镜像另配。步墙钟 720 秒要随之核对。
- 增加后台模式：`run_command(background=true)` 返回 `job_id`；`run_command` 的 handler 内部支持 `job_id` 读输出与 `kill`（沿用“改道不加工具名”的原则，用参数区分）。用于 dev server、watch 模式、长构建。
- 超时结果附最后 2KB 输出与“建议：加 timeout_s 或缩小测试范围（给出 -k / 单文件形式）”。

### 7.3 测试基线

现状：模型改完跑测试，看到失败，无法区分是自己改坏的还是原本就坏的。`test_summary` 已经能解析每条失败。

方案：Turn 内第一次运行某测试命令的结果记为基线（按命令归一化）。之后同一命令的结果附 `delta`：`newly_failing`、`newly_passing`、`still_failing`。receipt 与终态也用这个 delta 表述。这是三家都没有显式做、但成本很低的一项。

### 7.4 lint 自动回灌（产品模式）

Cursor 编辑后自动把新 lint 回灌并限次自修。本仓库的 `checks.new_issues` 已经回灌了单文件增量诊断，这一层基本到位。缺口在跨文件：改了函数签名，调用方的类型错误要靠模型主动调 `read_lints`。

方案：签名变化时（5.5 里的 AST 判断），对 impact 列出的引用文件跑一次诊断，只回增量。上限 5 个文件，预算 10 秒，超出则只给“建议 `read_lints` 这些路径”。

### 7.5 verify 闭环：从“催”转向“降成本 + 透明”

数据：receipt 发出率 0.80，发出后真正再跑测试 0.25；相关测试覆盖 1.0，采用 0.0。说明问题不是模型不知道，而是它判断不值得或不会跑。继续加重文案收益递减。

方案分三档，按模式启用：

1. **receipt 只给一条命令**（所有模式）。现在给最多 5 条相关测试加复现命令加失败摘要，模型面对清单倾向于全部跳过。改为平台排好序，只给最具体的一条（单测试文件，必要时带 `-k`），其余折叠成一行“另有 N 条”。
2. **编辑后钩子**（仅产品模式，用户可关）。参照 Claude Code 的 PostToolUse：Turn 结束前若 `verify_pending`，平台自己在 sandbox 跑那一条最具体的相关测试，结果以 tool_result 形态回灌给模型，再给它一次修的机会。评测模式关闭，保持“平台不代跑”。
3. **终态透明**（所有模式）。`turn.completed` 增加 `verification` 字段：`verified | unverified | failed | not_applicable`，附最后一次测试命令与 delta。Web 端在终稿上显示徽标。这不依赖模型配合，直接让用户知道哪些改动没验过。

### 7.6 issue 复现义务的过拟合风险

`structural/issue_repro.py` 的抽取规则里有 `Table.read/write` 的 `format=`、`header_rows=`、`ascii.xxx` 格式名、大小写折叠资产。这些规则来自 astropy-14182 和 14365 两道题，泛化价值有限，而且会让后续评测分数失去参考意义（规则拟合了题目）。

方案：

- 把抽取拆成**通用层**（围栏代码块、`>>>` REPL、报错原文、Expected 小节）与**领域插件**（astropy Table 往返、大小写折叠）。领域插件默认关闭，只在明确的评测对照实验中开启，并在 RESULTS 中标注。
- 产品模式下，“验收例子”从用户消息中抽取后写进 `update_plan` 的清单，作为可见的完成标准，而不是隐藏的义务。

### 7.7 收尾自检：最终 diff

现状 system prompt 要求模型自检“diff 非空、无未完成编辑、复现已重跑”，但平台没有给它 diff。

方案：终局边（与 receipt 同一位置）对产品模式注入一次 `git diff --stat` 与未跟踪的新文件列表（每 Turn 一次，有大小上限）。同时约定 `.agent/scratch/` 为临时复现脚本目录：不进 diff，Turn 结束提示清理。这样能抓到遗留的调试输出、误建的 `test.qdp`、`repro.py` 一类文件。

---

## 8. 第五层：上下文、规则与记忆

### 8.1 项目规则

现状：`context/project.py` 从工作区根读 `AGENT.md / agent.md / outline.md / AGENTS.md` 之一，上限 2000 字。

问题：2000 字放不下一个真实项目的约定（测试命令、代码风格、禁区目录、架构说明）；子目录规则无法生效；`outline.md` 是写作场景的文件，不该出现在编码的规则候选里。

方案：

- 读取 `AGENTS.md`（同时兼容 `CLAUDE.md`、`.cursor/rules/*.mdc` 的 `alwaysApply` 部分），根目录上限提到 8KB。
- **按路径生效**：模型读或改某路径时，把从根到该路径各级目录下的 `AGENTS.md` 追加进 `volatile_context`（每个文件每 Turn 只注入一次），总上限 24KB。`.mdc` 的 `globs` 匹配到被触碰的文件时同样注入。
- 规则进 `volatile_context`，不进 system，保持前缀缓存。
- 组窗压缩不得删除已注入的规则块，只能整体折叠为“规则 X 已加载（路径）”并允许重新展开。

### 8.2 工作集摘要

长 Turn 经过 collapse / snip / autocompact 后，模型会忘记自己改过哪些文件、哪些测试还红。

方案：`volatile_context` 每步附一个小块（上限 600 字）：

```
本轮已改：a.py(+12 −3) b.py(+1 −1)
未验证：a.py
最近测试：pytest tests/test_a.py → 2 failed（新增 1）
计划：3/5 完成
```

数据全部来自 TurnState，不额外调用模型。autocompact 的结构化摘要也要求保留这几项。

### 8.3 跨 Turn 记忆

`remember / recall / forget` 已有。编码场景值得自动沉淀的只有少数几类：项目的测试命令、构建命令、已知的环境坑（如“本仓库测试需要 `-p no:cacheprovider`”）。建议只在命令被成功使用且用户未拒绝时提议写入 `AGENTS.md`（由用户确认），而不是写进不可见的记忆表。理由是可审计、可版本控制，并且与 8.1 是同一条通道。

---

## 9. 第六层：规划与多代理

### 9.1 计划

Plan phase 已有，且有“只预授权清单内写盘、不预授权 shell”的正确区分。补充两点：

- `plan_suggest.threshold: 4` 依据的是什么信号需要在文档中写明；建议改为“跨 ≥3 个文件或用户消息含多个验收点”时建议进入 Plan。
- 计划项可挂验收命令（`acceptance: "pytest tests/test_x.py -k foo"`），计划项完成时 receipt 检查该命令是否在最近一次编辑后成功运行过。这把 7.5 的义务与用户可见的计划合到一处。

### 9.2 子代理

`subagent_types` 已有 explore / retrieve / verify / edit / planner / shell，上限 12 步。建议：

- **只读子代理可并行**（explore / retrieve 已有 `READONLY_DELEGATE_TYPES` 合并逻辑），适合大仓库的多点探索，结论以摘要回传，节省主窗口。
- **写盘只在主代理**。`edit` 子代理与主代理同时写同一工作区会破坏 4.2 的版本一致性；若保留，应让它在独立 worktree 里产出补丁，由主代理应用。
- **审阅子代理**（产品模式可选）：Turn 结束前把最终 diff 交给只读审阅者，按“遗留调试代码、未处理的错误路径、与 issue 不符、无关改动”四项给出意见，回灌主代理一次。成本是一次额外的模型调用，可以按 diff 大小触发。

---

## 10. 第七层：安全与权限

### 10.1 命令白名单不是安全边界

`agent.yaml` 的 `security.commands` 允许 `python`、`git`。`python -c` 可以做任何事；`git -c core.sshCommand=...`、`git config alias.x '!sh -c ...'` 也一样。白名单在这里只决定“要不要弹审批”，真正的边界是 sandbox。

方案：审批按**风险类别**判定，而不是按 argv0：

| 类别 | 例子 | 默认 |
|---|---|---|
| 只读 | `git status/diff/log`、`ls`、版本探测 | 免审 |
| 工作区内写 | 构建、测试、格式化 | 免审（sandbox 内） |
| 破坏性 | `git reset --hard`、`git clean -fdx`、`git push`、`rm -rf` 工作区根 | 每次审批 |
| 出网 | `curl`、`pip install`、`npm install` | 包注册表免审，其它审批 |
| 改执行配置 | 写 `.git/hooks`、CI 配置、`package.json` 的 scripts | 每次审批 |

### 10.2 出网

现状日常 sandbox 默认允许出网（Landlock 本身撤不掉出网）。编码 agent 会读取仓库里的任意文本（README、issue、依赖源码），其中可能嵌有提示注入，而出网是数据外泄的通道。

方案：

- sandbox 平面加出网代理：默认允许 PyPI、npm、crates.io、Go proxy、GitHub 的只读访问，其它域名首次访问需审批，并记入审计。
- 评测模式维持 bwrap `--unshare-net`，不变。
- 子进程环境已是默认拒绝继承，这一点保持。

### 10.3 失败后提权（参照 Codex）

现状 sandbox 不可用时直接拒绝；命令因 sandbox 限制失败（例如需要写 `~/.cache`）时，模型只看到失败。

方案：结果里识别 sandbox 拒绝的典型特征（EPERM / EACCES 指向工作区外路径），附 `sandbox_denied=true` 与被拒路径。产品模式下允许模型带理由请求一次“放宽重跑”（例如额外挂载一个可写缓存目录），走审批。

### 10.4 输出中的秘密

命令输出原样回灌模型并写入 `turn_events`。`env`、`printenv`、失败的配置加载经常打印凭据。建议对回灌的 stdout/stderr 做同一套秘密扫描并打码，原文不进耐久事件。

---

## 11. 第八层：产品体验

### 11.1 回退（checkpoint）

这是三家都有、本仓库缺失、且用户感知最强的一项。

设计：

- **影子 git**：每个 Work 在工作区外维护一个影子仓库（`GIT_DIR` 指向 Work 元数据目录，`GIT_WORK_TREE` 指向工作区）。不碰用户自己的 `.git`，不要求工作区本身是 git 仓库。
- **快照点**：每个 Turn 开始时提交一次；每次写类工具前，若该路径本 Turn 尚未快照，追加到当前快照（增量，成本低）。`run_command` 之后对变化的已跟踪文件同样记录（4.2 的 stat 结果可直接复用）。
- **操作**：撤销本 Turn（恢复到 Turn 开始）、撤销单个文件、对比任意两个快照。Web 端在每个 Turn 卡片上提供按钮。
- **与审批的关系**：快照写入成功才允许“可回退故免审”，取代现在只存在内存里的 `s1_snapshots`。checkpoint 只存快照 id，不再存文件内容。
- **限度**：工作区外的副作用（出网、数据库）无法回退，界面上要写明。

### 11.2 逐文件审阅

Turn 结束后列出本 Turn 改动的文件与 diff，用户可逐文件“保留 / 撤销”。撤销单文件后，下一 Turn 的 volatile_context 写明“用户撤销了 x.py 的改动”，避免模型下一轮又改回去。

### 11.3 权限模式

现有 `writes_preapproved / exec_preapproved` 是 Turn 内粘性。建议在会话级给用户三档：

| 模式 | 写盘 | 工作区内命令 | 破坏性 / 出网 |
|---|---|---|---|
| 询问 | 首次审批，本 Turn 粘性 | 首次审批 | 每次 |
| 自动编辑 | 免审 | 首次审批 | 每次 |
| 全自动 | 免审 | 免审 | 仍每次 |

依赖 11.1：没有可靠回退，不应提供“自动编辑”档。

### 11.4 运行中转向

现状“再对话 = 同 Session 新 Turn”。用户看到 agent 走错方向，只能取消再开，前面的读文件、复现全部丢失。

方案：运行中的用户消息写入 `run_commands`（与审批同一通道），Engine 在下一步边界把它作为用户消息追加，继续同一 Turn、同一 `run_id`。TurnState 与义务不丢失。取消仍是独立动作。

### 11.5 进度可见

`tool.delta` 已走活流。建议补两项：编辑的 diff 在审批前就流式渲染（现在要等 `approval.requested`）；长命令的输出尾部实时滚动。

---

## 12. 第九层：可观测与评测

### 12.1 新增指标

| 指标 | 含义 | 用途 |
|---|---|---|
| `edit_first_try_rate` | 首次 `edit_file` 即成功的比例 | 衡量 5.3、5.4 |
| `edit_match_mode` 分布 | exact / trailing_ws / reindent | 监控宽松匹配是否误改 |
| `edit_latency_p50/p95` 按阶段 | 诊断 / 引用 / 相关测试 | 衡量 5.5 |
| `stale_read_blocked` | 因 4.2 被拒或放行的次数 | 确认修复后不再误拒 |
| `unverified_finish_rate` | 终态 `verification=unverified` 比例 | 7.5 的主指标 |
| `receipt_followthrough` | receipt 后实际跑测试比例 | 现为 0.25 |
| `lsp_available` 按语言 | LSP 可用率 | 6.1 |
| `rollback_rate` | 用户撤销 Turn / 文件的比例 | 产品质量的反向指标 |

### 12.2 评测集

现状冒烟 n5 全部是 astropy，且多项启发式就是为其中两道题调出来的。风险是指标与能力脱钩。

建议：

- SWE-bench Lite 扩到 n25 以上（覆盖 django、sympy 等），已在 next 页列为缺口。
- 加 SWE-bench Verified 子集，以及一个多语言集（例如 SWE-bench Multilingual）验证 6.1。
- 加终端类任务集（如 Terminal-Bench）覆盖 7.2 的长命令与后台进程。
- 加少量“功能新增”类自建题（不是修 bug），检验 6.2 的自然语言定位与 9.1 的计划。
- 每次新增启发式规则，记录它是由哪道题触发的；在未参与调参的题上单独报告分数。

---

## 13. 路线图

### P0：正确性（1–2 周，均为小改动）

| 项 | 节 | 验收 |
|---|---|---|
| 字节保真编辑（换行、编码、BOM） | 4.1 | 四类文件编辑后 diff 只含目标行 |
| read_registry 按内容哈希判定 | 4.2 / 4.3 | 编辑后与 shell 改写后能重读；外部修改后 `write_file` 拒写 |
| `edit_file` 秘密扫描 | 4.4 | 单测覆盖 |
| `.git/**` 拒写，执行配置路径强制审批 | 4.5 | 单测覆盖 |
| 快照改为 `setdefault` | 4.6 | 同路径两次写后仍可恢复到 Turn 起点 |
| 移除 `slow_tool` | 4.7 | `agent.yaml` 不含桩工具 |
| 非 Python 代码文件也置 `verify_pending` | 6.1 | 改 `.ts` 后终局边发收据 |

### P1：原语与多语言（4–6 周）

| 项 | 节 |
|---|---|
| `edit_file(edits[])`、`replace_all`、匹配阶梯、写后片段 | 5.1 / 5.3 / 5.4 |
| 编辑延迟：基线缓存、写后并行、按需引用 | 5.5 |
| `LanguageSpec` 注册表；TS/JS、Go 首批 | 6.1 / 7.1 |
| grep 改道附词面命中；候选排序 | 6.3 / 6.4 |
| 自然语言查询 BM25；仓库地图 | 6.2 |
| `timeout_s` 参数与后台任务 | 7.2 |
| 测试基线与 delta | 7.3 |
| receipt 单命令；终态 `verification` 字段 | 7.5 |
| 分层 `AGENTS.md` 与按路径规则；工作集摘要 | 8.1 / 8.2 |
| issue 复现规则拆出领域插件 | 7.6 |

### P2：产品能力（6 周以上）

| 项 | 节 |
|---|---|
| 影子 git 回退、逐文件审阅 | 11.1 / 11.2 |
| 权限模式三档 | 11.3 |
| 运行中转向 | 11.4 |
| 产品模式编辑后钩子、最终 diff 自检、审阅子代理 | 7.5 / 7.7 / 9.2 |
| 风险类别审批、出网代理、失败后提权、输出打码 | 10.1–10.4 |
| 多文件补丁（按模型开关） | 5.2 |
| 语义代码索引（视 P1 评测结果） | 6.2 |

依赖关系：11.3 的“自动编辑”档依赖 11.1；7.5 的终态字段依赖 6.1（否则非 Python 永远是 `not_applicable`）；5.4 与 4.2 应同批上线，否则放开重读后模型会频繁整文件重读。

---

## 14. 不做的事

- **不在评测模式代跑测试。** 产品模式的钩子与评测完全隔离，`ops_eval` 下强制关闭。
- **不先上向量索引。** 先用 BM25 与仓库地图把自然语言定位的基线做出来，用评测决定是否需要 embedding。
- **不做模糊相似度匹配编辑。** 匹配阶梯只处理空白差异，且每级要求唯一。
- **不同时暴露 `edit_file(edits[])` 与 `apply_patch`。** 两套编辑格式会让模型在格式之间摇摆。
- **不把规则写进 system 提示。** 规则走 `volatile_context`，保住前缀缓存。
- **不为每项能力新增工具名。** 后台任务、读后台输出、`replace_all` 都是现有工具的参数。新增工具名只在 5.2 一处，且按 Profile 开关。

---

## 15. 风险与待定

1. **4.2 放开重读后的读放大。** 若模型在每次编辑后都整文件重读，组窗压力上升。缓解：5.4 的写后片段；重读结果在内容未变的区间返回“与上次相同”的短占位。需要评测确认。
2. **宽松匹配误改。** reindent 级可能在缩进敏感的语言（Python、YAML）里改错块。先只对 trailing_ws 默认开启，reindent 观察一轮再决定。
3. **多语言 LSP 的资源占用。** gopls、rust-analyzer 在大仓库上内存可达数 GB。需要按 Work 懒启动、空闲回收，并与 `RUNTIME_MAX_INFLIGHT_TURNS=16` 一起做容量规划。
4. **产品模式钩子的成本。** 每个 Turn 多跑一次测试，可能增加 10–60 秒。默认只跑最具体的一条，并允许用户关闭。
5. **影子 git 与大仓库。** 首次快照对大型 monorepo 有成本。可以只跟踪本 Turn 触碰过的文件，而不是整树。
6. **待定**：`plan_suggest.threshold` 的现行含义；`edit` 子代理是否保留；出网白名单由平台维护还是由租户配置。
