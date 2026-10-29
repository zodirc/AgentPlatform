# ADR-021 存储回收与可达性 GC

状态：提议。

## 结论

不整套照搬「目录 + 堆」的可达性回收。回收方式由数据形状决定。服务器和手机是两套存储，首版互不连接：

| 层 | 数据形状 | 在哪 | 手段 |
|---|---|---|---|
| 0 | 归属树：sessions → turns → runs → 子表 | 服务器 Postgres | 同步级联删除；时间序列表按月分区，保留期即删分区 |
| 1 | 内容寻址的消息块（仅在决定去重后才建） | 服务器 Postgres | 外键边表 + 反连接清扫 + 代数 |
| 2 | 影子 git、以 ID 为键的磁盘文件、无外键的引用行 | 服务器 `/data` 共享卷 | 以 Postgres 为根做标记、清扫、压缩，按 Work 执行 |
| 3 | 本地作品目录：快照对象、回合清单、事件、断点 | 本地接头（命令行、Android `:agent`、将来的桌面壳） | 以回合台账为根做标记、清扫，按作品执行，代码随内核发布 |
| 4 | 可重建的索引和易失缓存：Android Room、Redis | 各端 | 不做可达性回收；删掉重建，或靠 TTL / MAXLEN |

原则：能靠归属删除就别靠可达性；能靠删分区或删文件就别靠原地压缩；可重建的东西直接重建，不回收。

## 两套存储

手机首版不连本平台。`docs/android-writing-client.md` 的目标是断网以外不需要任何服务器，非目标包括不做账号、云同步，以及首版不连本平台。服务器的 Postgres、`/data` 和手机上的 `files/works/<id>/` 没有共同的根，作品也对不上号。

Android 与命令行壳共用的是 `app/writing_host` 里的同一份回收。代码随写作内核进 APK。这不是和服务器共用一个库，手机也不调用 api。

换机走 `export_work` / `import_work`，不经过本平台。

文档允许以后加 `RemoteBackend`，但不在首版。真要做时要重定谁是真源、保留期听谁的、对象按什么对齐。那些决定不从本 ADR 推导。本文件不把手机写成服务器的缓存，也不为「只上传缺少的块」预留协议。

## 标记—清扫的共同形状

第 1、2 层只在服务器。第 3 层只在接头，一份实现，命令行和 Android 都跑它。相同的只有下面几条。窗口、错误码、哈希各自定义，不要求两端一致。

**R1 根只来自权威源。** 服务器上，Postgres 是唯一的根；Redis、磁盘目录、内存都不算根。本地，作品目录是真相：根是回合台账（第 3 层），Room 只是索引。

**R2 扫不全就整轮放弃。** 以下任一情况，本单位本轮零删除，并记下原因：

- 根源读取失败或超时；
- 任一清单无法解析；
- 遇到 `schema_version` 高于本代码已知值的清单或台账。

最后一条针对内核回滚。Android 内核按 A/B 槽位热更新，可以回滚（`docs/android-writing-client.md` 第 9.4 节）。旧内核看不懂新格式清单里的引用；如果只按自己认识的字段做标记，会把还在用的对象当成孤儿删掉。

**R3 并发写入要有保护，不靠时钟。**

- 服务器库内：Postgres 上的 `gc_epoch` 代数，加外键行锁。
- 服务器跨存储：数据库和磁盘没有共同事务，标记事务的快照在提交后就不再成立。所以先列磁盘候选，再读根；删除集按库里的正向条件判定（终态、窗口外、过了宽限），不按「不在根里」判定；删引用用比较并交换。列举之后才出现的东西不在候选里，不会被删。
- 本地：作品级文件锁，回收和写入串行执行。
- 磁盘文件只把 mtime 当辅助的宽限期。mtime 不可靠：`/data` 是 HA 多副本共享的卷，各主机时钟有偏差；`zipfile.extractall` 导入时 mtime 全部变成当前时间；手机系统时间可以被用户随意改。所有「早于多久」的判断用 Postgres 的 `now()`，或者本地台账里单调递增的序号。

**R4 内容寻址的对象先写临时文件再 rename。** 对象按内容哈希命名，写入时如果「同名已存在就跳过」，那么崩溃留下的半截文件会被永久当成正确内容，撤销时就把坏内容恢复回稿里。所以：

- 对象写成 `tmp-*`，`fsync` 后再 `rename` 成最终名字，然后 `fsync` 父目录。只 `rename` 保证进程崩溃后不出现半截文件，断电后名字是否还在要靠父目录落盘；
- 同名对象已存在时读出来校验哈希，一致才跳过，不一致就用新内容走同一流程覆盖。文件存在、大小相同都不能证明内容正确；
- 清单最后写，也走临时文件加 `rename`；
- 读取对象时校验哈希，不一致就报错，不写回稿件。

**R5 回收可续跑、进度可见。**

- 服务器：进度写在 `gc_runs` 表里。
- 本地：通过接头调用 `gc_work` 返回统计结果，回收期间发进度回调。

进度都用「已删 / 候选」表示，候选数在开始时统计一次，之后固定不变。字段同名只为了命令行输出和手机诊断页好读，不是跨端协议。

**R6 接头错误只给本地壳。** 命令行和 Android 都读 `writing_host/errors.py` 的 `user_message`。下面三个加在这里，不加进 `packages/contracts`，不改 Web 的 `reduceTurn`，也不加 HTTP 状态码。手机不调用这些接口。

| 错误 | 场景 | 壳的处理 |
|---|---|---|
| `TurnNotRevertable` | 要撤销的回合已在本地保留窗口外。现在抛的是 `FileNotFoundError` | 撤销入口置灰并说明原因 |
| `StorageLow` | 开始回合或导出前，剩余空间低于阈值 | 回合不开始，提示清理。不在回合中途因写盘失败而 `turn.failed` |
| `SnapshotCorrupt` | 撤销时对象内容与哈希不符 | 不写回稿件 |

服务器上事件过期仍走现有保留期：客户端改读 `turn_views`。不为手机另造一个 `events_expired`。

**R7 保留窗口分两套。**

- 接头：`app/writing_host/schema.py` 的 `EVENT_KEEP_TURNS = 32`，按作品计数。命令行和 Android 窗口相同，因为跑的是同一份代码，不是因为要和 Web 上的撤销列表对齐。
- 服务器：影子 git 另定。写作 Work 用 `writing_revert_keep_turns`，代码 Work 用 `coding_revert_keep_days`，都按 Work 计数。不要求等于 32，也不和手机上某部作品对应。

**R8 哈希分两套。**

- 接头里的文件对象：对原始字节做 sha256，供本机快照和 zip 导入校验。
- 服务器第 1 层的 JSON 块：仅在决定去重之后定义，规范化参数留在服务器代码里。

两边不会拿哈希互相比对。

## 现状

### 服务器

技术栈：FastAPI 的 `api` 和 `runtime` 服务通过 asyncpg 访问 Postgres（检索用 pgvector）。Redis 只承担唤醒、任务流，以及 `EVENT_DURABILITY=checkpoint` 模式下的增量。HA 和执行平面部署（`deploy/compose/ha.yml`、`planes.yml`）中，多个副本共享 `agent_data:/data` 卷，Work 根目录在 `/data/works/{id}`。

**主路径是归属树，不是堆。** 没有跨会话共享的块。删会话时，`delete_sessions_for_owner`（`services/api/app/services/resource/sessions.py`）用 bypass 连接池开一个事务，逐表删除子行，相当于每块数据的引用计数恒为 1。

**会话删除**在 `turns` 还在时，用 `_delete_optional` 再删三张没有外键的表：`work_memories`（按 `session_id`）、`writing_fragment_evaluations`、payload 的 `turn_id` 指向这些 Turn 的 `outbox_jobs`。缺表只跳过该表。

**Work 删除**是 `delete_work_for_owner`（`services/api/app/services/resource/works.py`），路由 `DELETE /api/v1/works/{work_id}`。bypass 事务先锁 `works` 行，再 `FOR UPDATE` 锁该 Work 下的 `runs`。`status` 不是 `completed`、`failed`、`cancelled` 时（含 `waiting_approval`）抛 `WorkDeleteRefused`，事务回滚，不写墓碑，路由返回 409。否则删除该 Work 的会话、`work_memories`、`works`，同一事务插入 `work_tombstones(work_id, deleted_at)`。磁盘目录不在这个事务里删。

**周期任务**在 `_lease_reclaim_loop` 里，与事件保留共用 `LOCK_EVENTS_RETENTION`，按 `events_retention_interval_seconds` 触发。保留跑完后调用 `purge_expired_rows`：删除已消费或过期的 `turn_model_secrets`，以及 `expires_at < now()` 的 `work_memories`。预算读 `events_retention_budget_seconds`（`services/api/app/settings.py` 默认 25 秒）。预算在进入时已经耗尽则两张表都不删。

**写好了但没人调用：** `clear_session_transcript`。

**只增不减的表：** `outbox_jobs`、`run_commands`、`work_ast_index_jobs`、`runners`。

**按时间自动删除的有这些。** `run_events_retention`：流式增量保留 7 天，`turn_events` 其余事件保留 90 天，按所属 Turn 的终态和 `turns.updated_at` 判定，不按事件行自己的时间。`purge_expired_rows`：见上面的周期任务。`maintain_turn_event_partitions` 和 `maintain_series_partitions` 在同一把 `LOCK_EVENTS_RETENTION` 里、`purge_expired_rows` 之后调用，按下面的分区规则 `DROP` 过保留期的分区。上面列出的只增不减的表没有按时间删除。代码里从不执行 VACUUM。

**`turn_events` 按所属 Turn 的 `created_at` 做月分区。** 迁移 `0036_turn_events_partition` 在发现重复的 `(turn_id, sequence)` 时停下。旧表挂成历史分区，切换点是下个月 1 日。四个写入口的 `INSERT` 都用 `SELECT turns.created_at` 带出 `turn_created_at`：runtime 的 `append_event` 和 `event_writer`，api 的 `lease_reclaim` 和 `claim_timeout`（后两处调用 `event_sequence.insert_terminal_event`，不再各写一段取序号 SQL）。`append_event` 仍在 `UniqueViolationError` 上重试五次。主键是 `(event_id, turn_created_at)`，唯一约束是 `(turn_id, sequence, turn_created_at)`。`turn_events_notify` 挂在父表上，插入一行后 `pg_notify('turn_events_channel', turn_id)`，载荷是该行的 `turn_id`。空库从 `0001_phase0` 升到 `0041_gc_runs` 后父表的 `relkind` 是 `p`。分区里还有非终态 Turn 时不删，并给 `gc_aborted{layer="0",reason="partition_pinned"}` 加一。

`session_raw_snapshots`、`model_request_envelopes`、`projection_log` 按 `created_at` 分区，主键是 `(id, created_at)`。`audit_log` 没有 `created_at`，按 `ts` 分区，主键是 `(id, ts)`，`audit_log_id_seq` 仍归父表的 `id`。四张表各一次迁移：`0037_raw_snapshots_partition`、`0038_model_envelopes_partition`、`0039_projection_log_partition`、`0040_audit_log_partition`（文件名可更长；`revision` 不超过 32 字符）。切换点都是下个月 1 日；切点上已有行时迁移停下，不改名、不挂载。旧表挂成历史分区。`session_raw_snapshots` 指向 `sessions` 的外键建在父表上，带 `ON DELETE CASCADE`。这四张表的分区上界早于 `now() - events_structural_retention_days`（`services/api/app/settings.py` 默认 90）时，`maintain_series_partitions` 删掉该分区；上界还在保留期内则不删。`turn_events` 的非终态挡住整月这一条只用于 `turn_events`。`services/api/app/db/table_repack.py` 的 `repack_argv` 在空闲空间小于表大小的 1.2 倍时返回空列表，并写 warning，原因是 `disk_low`，不拼 `pg_repack` 命令。空间够时返回 `pg_repack --table <表名>`。决策没有给出「已经膨胀」的数值，定时任务不自行挑选表。

**按步存全量消息，存储随步数平方增长：**

- `raw_snapshot_enabled` 默认关（`services/runtime/app/settings.py`）。安全审计写在 `audit_log`，不读逐步全量快照，所以按第 1 档停在这里，不建 `blobs`。`append_raw_snapshot` 在开关打开时仍每步写完整 messages，成功后把字节数加进 `storage_step_write_bytes`。
- `model_envelope_sample_rate` 默认 0.01（`services/runtime/app/settings.py`）。`content_hash` 每步照写。完整 body 只在抽样命中、`model_envelope_debug`，或 fill 达到 `context_fill_autocompact` 时写入；写出的 body 字节同样计入 `storage_step_write_bytes`。抽样命中时，按 `canonical_json`（键排序、保留非 ASCII）给每条消息算 sha256。本进程内已经提交过的哈希，其规范字节计入 `storage_canonical_hit_bytes`，分母是 `storage_canonical_bytes`。已见集合上限 100000，满了之后新哈希不算命中。插入失败不提交哈希。这不是内容寻址堆，也不跨进程。

**影子 git（`policy/shadow_git.py`）的新提交不再接在 HEAD 上：**

- 每个回合用 `index-{turn}`。基线是 `commit-tree` 且不带 `-p`。后续 preimage 以本回合标签为父，再用 `update-ref refs/tags/turn/{id} <新> <旧>` 比较并交换。比较并交换失败则标签停在原 SHA，本回合 index 删掉，该路径不记成已录。
- `_ensure_repo` 把 `gc.auto` 设为 0。回合写入不调用 `git gc`。`mark_work` 在没有非终态 run 时压缩：存量迁移之后一次，标签清扫之后再一次。有非终态 run 时跳过压缩，标签清扫照常。`git gc` 使用 `--prune=1.hour.ago`。
- 回合进入 `completed`、`failed` 或 `cancelled` 之后删除 `index-{turn}`。`waiting_approval` 不删。
- 撤销接口 `POST /rollback/turn` 在事务里对 `hashtextextended(work_id)` 拿 `pg_advisory_xact_lock_shared`，确认 Turn 仍在窗口内，把标签解析成 SHA 再按 SHA 恢复。写作场景的窗口是该 Work 最近 `writing_revert_keep_turns` 个 Turn（`settings.py` 默认 20）。其它场景要求 `turns.updated_at` 落在 `coding_revert_keep_days`（默认 7）以内。窗口外或没有标签返回 409，不改工作区。确认失败返回 503，不改工作区。
- `mark_work` 拿不到排他锁就跳过。Work 根目录不可读则 `aborted="work_unreadable"`。`git for-each-ref` 失败则 `aborted="git_list_failed"`。旁路目录列举失败则 `aborted="side_list_failed"`。这三种和数据库查询失败都是候选 0，并写入 `gc_runs`，`deleted` 为 0。候选按列举当时的标签计算，列举之后新建的标签不在其中。非终态 Turn、窗口内的 Turn，以及 `updated_at` 还在 1 小时宽限内的 Turn 不是候选。
- 没有非终态 run 时，在同一把排他锁内把窗口内有父的标签改成无父提交，删掉 `refs/heads/*`，HEAD 指向空树的孤儿提交，然后压缩。空闲空间小于 `git count-objects -v` 的 `size` 加 `size-pack` 时不压缩，`abort_reason="disk_low"`。磁盘不足只跳过压缩，标签仍按删除集清扫。有非终态 run 时不改存量标签，也不压缩。
- 清扫只处理列举当时的标签。`git update-ref -d refs/tags/turn/{id} <列举时的 SHA>` 失败则留下该标签和它的 `recorded/`、`absent/`。删除成功后，mtime 早于 `now()` 减 1 小时的 `recorded/`、`absent/` 才删。Turn 不存在时，同样宽限下的 `.agent/thinking/{turn_id}.jsonl` 才删。传入隔离目录时，`expires_at` 已过或 owner Turn 不存在的 `quarantine/{id}.*` 才删，mtime 仍在宽限内的文件留下。有墓碑且 `deleted_at` 早于宽限时删除工作目录和 `.agent-shadow/{name}`，再删墓碑行。没有墓碑也没有 `works` 行的目录留下，记一条 warning，并给 `gc_candidates{layer="2"}` 加一。`work_memories` 里 `session_id` 非空且会话已不存在的行在这次清扫里删除。本轮实际删掉的个数写入 `gc_runs.deleted`。同一标签再跑一轮时 `deleted` 为 0。
- api 按 `work_gc_enqueue_interval_seconds`（`services/api/app/settings.py` 默认 86400）入队。同一个 Work 已有 `pending`、`retry` 或 `processing` 的 `work_gc` 时不再插入。删除 Work 的事务在墓碑之后入队；批量删除会话的事务在删行之后，按这些会话的 `work_id` 入队。runtime 的 `claim_and_mark_once` 用 `FOR UPDATE SKIP LOCKED` 只领取 `work_gc`，先列盘，再在 `REPEATABLE READ` 只读事务里读根。api 的 `claim_jobs` 排除 `work_gc`。
- 回合进行中的影子写入不拿这把锁。`lease_reclaim` 仍可能在租约过期时把 run 判为 `failed`，原副本还活着时会继续写标签；比较并交换失败的那次写入不会盖掉后写的 SHA。

**跨存储的孤儿：**

- `{data_dir}/quarantine/{id}.*`：读取时按 7 天 TTL 拒绝过期项。`claim_and_mark_once` 把该目录交给 `mark_work`，按上面的隔离目录规则删除。
- `{work_root}/.agent/thinking/{turn_id}.jsonl`。
- `{work_root}/../.agent-shadow/{name}`。

**同一会话的 turn 并发覆盖。** 两个 turn 可以同时执行，`session_transcripts` 由后写者整行覆盖。

### 本地接头（`app/writing_host`）

作品目录以 `.agent/turns.json` 为根，`seq` 在 `start_turn` 里分配。`list_turn_history`、`revert_turn`、`gc_work` 都按它排序。没写稿的回合 `snapshot` 为 false，不出现在撤销列表里，照样占 `EVENT_KEEP_TURNS`。

- **锁：** `.agent/lock` 上的 `fcntl.flock`。`start_turn` 到终态的写盘、`snapshot_turn`、`revert_turn`、`write_document`、`gc_work` 在锁内。`import_work` 锁的是暂存目录。拿到锁后先对账：`running` 有断点改为 `interrupted`，没有改为 `failed`。
- **快照：** `snapshot_turn` 仍挂在 `before_apply` 上。对象先校验已有内容的哈希，临时文件 `fsync` 后 `rename`，再写清单，最后把台账的 `snapshot` 置上。
- **回收：** `gc_work` 在终态事件之后和 `revert_turn` 之后执行。根是 `seq` 最大的 32 个回合，加上 `running` 和 `interrupted`。台账或清单扫不全则本轮零删除，`deleted` 为 0。非根回合的清单已经删掉时，下一轮接着清扫，不把这次中断当成损坏。Python 报告字段是 `candidates`、`deleted`、`aborted`、`bytes_reclaimed`。命令行 `--gc` 只打印一行 JSON，字段换成 `gc_marked`、`gc_candidates`、`gc_deleted`、`gc_aborted`、`gc_bytes_reclaimed`；放弃时后两个数量为 0。
- **导出：** `export_work` 默认 `manuscript`，不含快照、事件和断点。`full` 带回合历史。`import_work` 在作品列表外的 `import-staging/` 校验路径、符号链接和对象哈希，通过后 `rename` 成作品目录。
- **错误：** 窗口外的撤销抛 `TurnNotRevertable`。剩余空间低于 64 MB 时先回收，仍不够抛 `StorageLow`，回合不开始。撤销时对象哈希不符抛 `SnapshotCorrupt`，不写回稿件。

### Android（`docs/android-writing-client.md`，未落地）

- 「文件是真相，数据库只是索引」：Room 可以重建。
- 回合只在 `:agent` 进程的前台服务里执行，空闲时不常驻。
- 全应用同一时刻只有一个回合（A16）。
- 内核 A/B 槽位在 `files/core/`。
- 有进行中或待恢复的回合时，不切换内核、不安装 APK。
- 设置页有「清理」入口，要求经接头执行，不由壳直接删目录。

## 第 0 层：归属删除与分区（服务器）

1. **补齐会话删除。** 在 `delete_sessions_for_owner` 中补删漏掉的表，每张可选表仍包在 savepoint 里执行，沿用 `_delete_optional`。
2. **新增 Work 删除。** 在 bypass 连接池的事务里：先对该 Work 下的 `runs` 加 `FOR UPDATE`，存在非终态 run（含 `waiting_approval`）就拒绝删除；然后依次删除该 Work 下的所有会话（复用第 1 步）→ `work_memories` → `works`，同一事务写入 `work_tombstones(work_id, deleted_at)`。磁盘目录不在这个事务里删，交给第 2 层按墓碑回收。
3. **挂上周期任务。** 现有清理函数和过期行删除，挂到 api 的 `_lease_reclaim_loop`。沿用它的约定：会话级 advisory lock，每次 25 秒预算。

**时间序列表按月分区：** `turn_events`、`session_raw_snapshots`、`model_request_envelopes`、`audit_log`、`projection_log`。保留期到了就直接删分区，用 Alembic 迁移实施。

**原因：** Postgres 的 `DELETE` 只留下死元组。autovacuum 让表内空间可以复用，但不还给操作系统。`VACUUM FULL` 持有 ACCESS EXCLUSIVE 锁，还需要约等于表大小的额外空间，在线服务不可接受。删分区只改元数据，瞬间完成，空间立刻归还。

分区表的主键和唯一约束必须包含分区键。`session_raw_snapshots`、`model_request_envelopes`、`projection_log` 只有代理主键（`id`），改成 `(id, created_at)` 不改变语义，按 `created_at` 分区。`audit_log` 的时间列是 `ts`，主键改为 `(id, ts)`，按 `ts` 分区。

**`turn_events` 按所属 Turn 的创建时间分区，不按事件时间。**

- 新增列 `turn_created_at`，值取 `turns.created_at`，写入后不变。分区键对 `turn_id` 函数依赖，所以 `UNIQUE(turn_id, sequence, turn_created_at)` 与原来的 `UNIQUE(turn_id, sequence)` 等价，数据库仍然兜底，`append_event` 的 `UniqueViolationError` 重试照常生效。主键改为 `(event_id, turn_created_at)`；没有外键指向 `event_id`。
- 一个 Turn 的全部事件落在同一分区。按 `ts` 分区时，跨月的 Turn 会被删掉前半截事件，而保留期本来就按 Turn 判定。
- 四个写入口统一走 `next_sequence`，`INSERT` 用 `SELECT ... FROM turns WHERE id = $turn_id` 带出 `turn_created_at`。`lease_reclaim`、`claim_timeout` 里复制的取序号 SQL 删掉。
- 月分区 M 可以删的条件：分区里没有非终态 Turn，且 `max(turns.updated_at) < now() - events_structural_retention_days`。长期挂起的 Turn 会挡住整个分区，`gc_aborted{layer="0",reason="partition_pinned"}` 记下。
- 流式增量的 7 天保留仍是分区内 `DELETE`。表到了稳态，autovacuum 回收的空间被新增量复用，不需要还给操作系统。

**`turn_events` 迁移步骤：**

1. 迁移前检查：`GROUP BY turn_id, sequence HAVING count(*) > 1` 必须为空；有重复就停下，不迁移。
2. 旧表补 `turn_created_at` 并分批回填，之后设 `NOT NULL`；加 `CHECK (turn_created_at < 切换点)` 时先 `NOT VALID` 再 `VALIDATE`，不长时间持锁。用 `CREATE UNIQUE INDEX CONCURRENTLY` 在旧表上预建与父表一致的两个唯一索引，挂载时直接复用。
3. 建分区父表，在同一事务里把旧表改名后 `ATTACH` 为一个历史分区（有已验证的 CHECK，挂载不再扫表），父表接过原表名，在父表上重建 `NOTIFY` 触发器和 `turn_events_insert_role` 的授权。
4. 切换点之后的 Turn 进月分区。历史分区作为一个整体，等其中最后一个 Turn 过保留期后一次删除，`turn_events` 不需要 `pg_repack`。
5. 回退：新分区还没收到写入之前，`DETACH` 后改回原名即可；有了写入之后只向前修。

**存量膨胀：** 已经膨胀的非分区表用 `pg_repack` 在线重写。执行前检查空闲空间不少于表大小的 1.2 倍，不够就不执行并告警。

**Redis 不参与回收（第 4 层）。** 任务流已经用 `XADD maxlen=100_000, approximate=True` 限长。增量流和唤醒键必须带 TTL 或 MAXLEN；新增 Redis 键时，在代码评审中检查这一点。

## 第 1 层：内容寻址堆（服务器，可选）

**先量，再决定建不建。** 每个 step 存截至当前的全部消息，一个 \(n\) 步的 Turn 累计写入 \(\frac{n(n+1)}{2}\) 份消息，但平方增长不等于必须内容寻址。按下面的顺序判定，前一档能满足就停：

1. 审计不要求逐步快照：`raw_snapshot_enabled` 默认关，`model_envelope_sample_rate` 降到 0.01 量级（哈希照写）。本层不做。
2. 要求能还原每一步、但不要求每步独立存全量：每个 step 只存相对上一 step 追加的消息，每 K 步或前缀被改写（组窗压缩、截断）时存一份全量检查点，读取时从最近检查点往后拼。行仍归属 Turn，随第 0 层删除，不需要可达性回收。
3. 重复主要发生在 Turn 之间、会话之间（同一系统提示、同一批工具结果被反复带上），第 2 档省不掉：才建本层。

判定用的数字来自落地顺序第 3 步的测量：每 step 的写入字节，以及抽样里按 R8 规范化后命中已有块的字节占比。本层的成本也一并算进去：`blobs` 的 jsonb 和 TOAST、每条消息一行 `blob_refs`、两张表的索引、WAL 和外键检查。去重省下的字节要明显超过这些开销才建。

### 结构

```sql
blobs(
  hash          text PRIMARY KEY,        -- R8：规范化 JSON 的 sha256
  body          jsonb NOT NULL,
  size          int  NOT NULL,
  touched_epoch bigint NOT NULL
)

blob_refs(
  owner_kind text   NOT NULL,            -- raw_snapshot | envelope | transcript | checkpoint
  owner_id   uuid   NOT NULL,
  step       int    NOT NULL,
  ord        int    NOT NULL,
  hash       text   NOT NULL REFERENCES blobs(hash) ON DELETE RESTRICT,
  PRIMARY KEY (owner_kind, owner_id, step, ord)
)

gc_epoch(id int PRIMARY KEY DEFAULT 1, epoch bigint NOT NULL)

gc_runs(
  id uuid PRIMARY KEY, scope text, epoch bigint, phase text,
  candidates bigint, deleted bigint, cursor text,
  abort_reason text, started_at timestamptz, finished_at timestamptz
)
```

**引用只放在边表里，不藏进 JSONB。** 原因有两个：

- 回收时不用解析 JSON，避免解析逻辑和写入逻辑不同步导致扫不全。
- 外键检查本身就是写屏障。

### 写入

在同一个事务内完成：

1. 读取 `gc_epoch.epoch`，记为 `E`。
2. `INSERT INTO blobs ... ON CONFLICT (hash) DO UPDATE SET touched_epoch = E`。
3. 插入 `blob_refs`。

**重用已有块时也必须刷新 `touched_epoch`。** 一个块上一轮已经成为孤儿、这一轮又被新消息命中时，如果只看创建代数，它会被当成孤儿删掉。

### 清扫

标记和清扫合成一条带反连接的删除：

```sql
DELETE FROM blobs b
WHERE b.hash IN (
    SELECT hash FROM blobs
    WHERE touched_epoch < $E - 1 AND hash > $cursor
    ORDER BY hash LIMIT 1000
)
AND NOT EXISTS (SELECT 1 FROM blob_refs r WHERE r.hash = b.hash)
RETURNING hash
```

**一次回收的步骤：**

1. 获取 `pg_try_advisory_lock('blob_gc')`，拿不到就本轮跳过。
2. 在同一个事务里推进 `gc_epoch` 并写入 `gc_runs`。
3. 用 bypass 连接池按哈希游标分批删除，每批一个短事务。每批结束后更新进度。
4. 时间预算用完就保存游标并退出，下一次从游标继续。

### 并发安全

**多落后一代：** 有的写事务在推进代数之前就读到了旧代数，但还没提交。`touched_epoch < E - 1` 多留一代覆盖这个窗口。

**真正的安全来自外键：** 写入方插入 `blob_refs` 时，外键检查会对对应的 blob 行加 `FOR KEY SHARE` 锁：

- **删除先拿到这行：** 引用插入因外键失败，写入方重新插入 blob 后重试。
- **插入先拿到这行：** `DELETE` 要么等待行锁，要么重新检查时看到这条引用。

两种情况都不会删掉正在被引用的块。

### 归属删除与 transcript 乐观锁

会话删除时只删 `blob_refs`，相当于只摘掉目录头；`blobs` 一律交给本层回收。

`session_transcripts` 改成哈希清单时，同时加上 `version` 列，写入时做比较并交换，冲突就重读、合并后再写。否则同一会话两个 turn 互相覆盖时，被覆盖一方写入的块会全部变成孤儿。

## 第 2 层：跨存储回收（服务器）

覆盖范围：影子 git、thinking 旁路文件、隔离区文件、`.agent-shadow/` 目录、已删 Work 的 `/data/works/{id}`、无外键的引用行。

**在哪里执行：** 在 runtime 服务里执行，因为它挂载了 `/data` 并且有 git。api 的周期任务只负责入队一个 `work_gc` 任务（outbox，单 Work 去重），runtime 用 `FOR UPDATE SKIP LOCKED` 领取。

**锁：** 用 Postgres 上每个 Work 一把的 advisory lock，做法与 AST 索引器的锁相同。`work_gc` 用 `pg_try_advisory_lock` 拿排他锁，拿不到本 Work 本轮跳过；runtime 的撤销接口在一个事务里拿 `pg_advisory_xact_lock_shared`，在锁内确认目标 Turn 仍在窗口内，把 `turn/{id}` 解析成提交 SHA 后按 SHA 恢复。窗口外直接返回不可撤销，不做部分恢复。回合进行中的影子写入不拿这把锁，安全由下文的删除条件和 prune 宽限保证；否则 `waiting_approval` 挂几个小时，这个 Work 就一直回收不了。不用文件锁：`/data` 是多副本共享卷，跨主机的 `flock` 不可靠。

### 前置改造：影子 git 的提交结构

- 每个回合的基线改成没有父提交的孤儿提交：用独立的 `GIT_INDEX_FILE`（路径 `index-{turn}`）`git add`，`write-tree` 后 `commit-tree` 且不带 `-p`。
- 同一回合后续的 preimage 提交以本回合标签为父：`commit-tree -p turn/{id}`，再 `update-ref refs/tags/turn/{id} <新> <旧>` 比较并交换。HEAD 不再移动。
- 回合结束后删除 `index-{turn}`。
- `_ensure_repo` 设 `gc.auto=0`，压缩只由 `work_gc` 发起。

各回合的提交链互不相连，删掉标签才能让这条链不可达。树和 blob 仍按内容在回合之间共享，这是正常的：回收的单位是「不可达对象」，删一个标签只释放它独有的对象。回合标签的树也不再带上更早回合的文件。

**存量仓库迁移：** 对窗口内的每个标签，取它的树 `commit-tree` 出一个无父提交并改指过去；删掉 `refs/heads/*`，HEAD 指向一个空树的孤儿提交；然后照常压缩。迁移在 `work_gc` 的排他锁内、该 Work 没有非终态 run 时执行。

### 标记

顺序固定为先列盘、后读库（R3）：

1. **列举：** `git for-each-ref --format='%(refname) %(objectname)' refs/tags/turn/`，记下每个标签当时指向的 SHA；列出 `recorded/`、`absent/`、`.agent/thinking/`、`quarantine/`。
2. **读根：** 在一个 `REPEATABLE READ` 的只读事务里，对第 1 步列出的每个 turn_id 查出它是否存在、run 是否终态、`turns.updated_at`、是否在本 Work 的窗口内（写作 Work 取 `writing_revert_keep_turns`，代码 Work 取 `coding_revert_keep_days`）；同一事务读 Work 是否存在和 `work_tombstones`，以及 `now()`。

Turn 行在 runtime 第一次写影子提交之前就已提交，所以第 2 步一定能看到第 1 步列出的标签对应的 Turn；第 1 步之后才建的标签不在候选里。这一轮的标记快照在事务结束后就过期，清扫只依赖它算出的删除集，不再把它当成「此刻的根」。

以下任一情况，本 Work 本轮零删除，并把原因写入 `gc_runs.abort_reason`（R2）：

- 数据库查询失败或超时；
- Work 根目录不可读；
- `git for-each-ref` 失败；
- 旁路目录列举失败。

### 清扫

删除集按正向条件判定。「宽限」都以第 2 步读到的 Postgres `now()` 为准，取 1 小时，要大于租约超时：`lease_reclaim` 判死的副本可能还活着，还在写这个回合。

| 对象 | 删除条件 |
|---|---|
| `turn/*` 标签 | Turn 不存在；或 run 终态、在窗口外、`updated_at` 早于宽限 |
| 该标签的 `recorded/`、`absent/` 文件 | 标签删除成功之后 |
| `.agent/thinking/{turn_id}.jsonl` | Turn 不存在 |
| `quarantine/{id}.*` | 已过 7 天 TTL，或 owner 已经不存在 |
| `.agent-shadow/{name}`、`/data/works/{id}` | 有墓碑且 `deleted_at` 早于宽限；删完再删墓碑。没有墓碑、也没有 `works` 行的目录只计入 `gc_candidates` 并告警，不删 |
| `work_memories`（`session_id` 非空） | 会话已经不存在 |

**标签用比较并交换删除：** `git update-ref -d refs/tags/turn/{id} <第 1 步的 SHA>`。失败说明标签在列举之后被移动过（还活着的旧副本在写），本标签本轮跳过，`recorded/`、`absent/` 不动。旧副本在删除之后又 `tag -f` 建回来的标签，下一轮再删；它新写的对象受下面的 prune 宽限保护。

磁盘文件另有 mtime 宽限：mtime 晚于「Postgres `now()` 减 1 小时」的文件不删。共享卷上各主机时钟有偏差，所以宽限期要远大于偏差。mtime 只是辅助，删除依据仍是上表的库内条件。

### 压缩

```bash
git reflog expire --expire=now --all
git gc --prune=1.hour.ago
```

**不能用 `--prune=now`。** `snapshot_preimage` 先 `git add`（对象已写入，但还没被引用），再 `commit`。git 的 prune 宽限期就是它自带的代数机制，专门保护这个窗口。新回合写入的内容如果命中一个旧的、已不可达的对象，git 写对象时会刷新它的 mtime，所以「复活」的对象同样落在宽限期内。压缩与回合写入并发时的正确性靠这一条，不靠跳过活跃 run。

**执行条件：**

- 压缩前用 `git count-objects -v` 的 `size` 加 `size-pack` 估算峰值，空闲空间不足这个数就跳过并记 `abort_reason="disk_low"`。这只是第一道门，不证明压缩过程不会写满磁盘；
- `git gc` 带超时执行。失败（含磁盘写满、超时）记入 `abort_reason`，旧 pack 在新 pack 写完之前不会删除，残留的临时 pack 由下一轮的 prune 清掉；
- Work 有活跃 run 时，本轮跳过压缩，省的是 I/O；标签清扫照常执行。

## 第 3 层：本地作品目录（本地接头）

回收代码放在 `app/writing_host`，随写作内核一起发布。命令行壳、Android 和将来的桌面壳运行的是同一份实现。壳不碰 `.agent/` 下的任何路径，符合「稿树不透明」。

### 回合台账：本地的目录

新增 `.agent/turns.json`，带 `schema_version`，加入 `SCHEMA_VERSIONS`：

```json
{
  "schema_version": 1,
  "next_seq": 41,
  "turns": [
    {"turn_id": "…", "seq": 40, "created_at": "…", "state": "completed"}
  ]
}
```

- **`seq` 是唯一的顺序依据。** 它是单调递增的整数，由接头在 `start_turn` 时分配，条目在回合第一次写盘之前落盘。`list_turn_history`、`revert_turn`、保留期都按它排序，不再看文件名或 mtime。这修复了现状里 `revert_turn` 丢错回合的问题。
- **`state` 取值：** `running`、`interrupted`（`listResumable` 的来源）、`completed`、`failed`、`cancelled`。
- **`snapshot` 字段：** 清单落盘之后才置 `true`。没写稿的回合没有清单，`snapshot` 保持 `false`，不出现在撤销列表里，但照样占保留窗口。
- **写入方式：** 每次用临时文件加 `rename` 原子替换，`rename` 后 `fsync` `.agent/`。
- **兼容旧作品：** 首次打开没有台账的旧作品时，按清单里的 `created_at` 迁移生成台账；只有 `created_at` 缺失时才退回到 mtime，并在台账里记下 `migrated_from_mtime: true`。

### 打开时对账

接头每次拿到作品锁后、做任何写入或回收之前，先按下表把台账和磁盘对齐。拿到锁本身说明没有别的进程在写这个作品。

| 磁盘上的情况 | 从哪来 | 处理 |
|---|---|---|
| 条目 `running` | 进程在回合中途死掉 | 有断点改为 `interrupted`，没有断点改为 `failed`。两种都不当垃圾 |
| 条目 `snapshot: false`，清单存在且能解析 | 清单 `rename` 之后、台账更新之前崩溃 | 置 `snapshot: true`。清单是 `rename` 出来的，要么完整要么不存在 |
| 条目 `snapshot: true`，清单缺失或解析失败 | 磁盘损坏或外部改动，正常写入顺序下不会出现 | 不修复；本轮回收放弃，`aborted="manifest_corrupt"` |
| 清单存在，台账里没有条目 | 外部拷进来的文件，或迁移漏掉的 | 接在 `next_seq` 之后补一条 `completed`，记 `recovered: true`，不删 |
| 对象存在，没有清单引用；残留 `tmp-*` | 对象写完、清单写入前崩溃 | 不在这里处理，交给清扫 |

### 作品锁

`.agent/lock` 用 `fcntl.flock`（Chaquopy 自带的 CPython 支持）。以下操作都在锁内执行：

- `start_turn` 到终态之间的写盘；
- `snapshot_turn`、`revert_turn`、`write_document`、`gc_work`；
- `import_work` 锁的是暂存目录，见「导出与导入」。

本地是单机单文件系统，作品锁足以替代代数（R3）。Android 上的单消费者队列是第一道保证，作品锁是第二道，并兼顾命令行多进程的情况。

### 标记

**根的组成：**

- 台账中 `seq` 最大的 `EVENT_KEEP_TURNS` 个回合；
- 所有 `running` 和 `interrupted` 状态的回合。

待恢复的回合在用户放弃之前一直是根，不会因为后面又开了 K 个回合而被挤掉。

**引用的来源：** 根回合清单里的 `files[].sha256`。

**放弃条件（R2）：** 台账或任一清单无法解析，或者 `schema_version` 高于 `SCHEMA_VERSIONS` 中的已知值，本轮放弃。返回 `GcReport(aborted="manifest_schema" | "manifest_corrupt" | "ledger_corrupt")`，壳在「诊断」页展示。

### 清扫

- 不在根里的回合：删除它的清单、事件、断点、评分，以及台账条目。
- 不被任何根清单引用的 `objects/*`：删除。
- 残留的 `tmp-*` 文件：删除。持锁期间它们只可能来自崩溃，可以放心删。

文件删掉后空间立刻归还文件系统，本地不需要压缩步骤。这是「一个对象一个文件」相对于把对象打成一个 SQLite 或打包文件的主要好处。代价是每个小文件至少占用一个块，但稿件按章节存，文件数在百级，这个代价可以接受。

### 触发

- 回合到终态之后。现状里 `snapshot_turn` 之后和 `FileEventLog.append` 每行之后的两处调用都删掉：前者发生在回合开始写稿时，后者让每条事件都扫一遍目录。
- `revert_turn` 之后（新增）。
- 壳调用 `gc_work(work_root, budget_ms)`（新增协议入口）。

**不阻塞终态事件。** 接头先发出 `turn.completed` / `turn.failed` / `turn.cancelled`，再在 `budget_ms` 内执行回收；预算用完就留到下次。

### 写入顺序（R4）

1. 对象：目标已存在时读出来算 sha256，与文件名一致才跳过；不存在或不一致，写成 `tmp-<rand>`，`fsync` 后 `rename` 为 `<sha256>`，覆盖坏对象。稿件按章节存，文件数在百级，每次快照多读一遍已有对象可以接受。
2. 本回合的对象都 `rename` 完之后，`fsync` 一次 `objects/` 目录。
3. 清单：临时文件，`fsync`，`rename`，`fsync` `turns/` 目录。
4. 台账：置 `snapshot: true`，按台账的写入方式落盘。
5. `revert_turn` 读取对象时校验 sha256，不一致就抛 `SnapshotCorrupt`，不写回稿件。

每一步都在前一步落盘之后开始，所以「台账说有快照」蕴含「清单和它引用的对象都已落盘」，打开时对账只需要处理上表里的几种情况。这依赖目录 `fsync` 在作品所在的文件系统上生效：命令行壳所在的本地文件系统和 Android 应用私有目录（ext4 / f2fs）满足；SAF 导出目标不是作品目录，不受这条约束。

### 导出与导入

**`export_work(mode)` 分两种模式：**

- **`manuscript`：** 稿件加侧车，不含 `.agent/snapshots`、事件、断点。这是自动导出的默认模式。
- **`full`：** 带上回合历史，用于换机。

**`import_work` 先在暂存目录里验证，最后一步才成为作品：**

1. 目标作品目录必须不存在，不往已有作品里解压。
2. 在同一卷上、作品列表之外建 `import-staging/<rand>/`，在它里面拿作品锁。暂存目录不在作品列表里，Room 对账看不到它。
3. 逐条检查 zip 条目：拒绝绝对路径、含 `..` 的路径、符号链接（`external_attr` 的文件类型位）、重名条目，再解压。不依赖 `zipfile.extractall` 自己的路径清洗。
4. 校验 `export.json` 的 `schema_versions`，以及台账和每份清单自己的 `schema_version`；逐个校验对象的哈希与文件名一致。
5. 丢弃台账中 `snapshot: true` 却缺少清单的回合；在暂存目录上跑一遍打开时对账；用当前时间重建 `seq` 顺序之外的元数据，旧 mtime 不作为依据。
6. `fsync` 后把暂存目录 `rename` 成目标作品目录，返回 `work_view`。壳只在这之后登记 Room。

任一步失败就删掉暂存目录，不留下半个作品。接头启动时删掉残留的 `import-staging/*`，那只能是崩溃留下的。

### 存储空间

`start_turn` 和 `export_work` 开始前，接头检查作品所在卷的剩余空间：

- 低于阈值时，先做一次 `gc_work`；
- 回收后仍不够，抛 `StorageLow`（R6）。

阈值默认 64 MB，壳可以通过参数覆盖。Android 上，壳可以先用 `StorageManager.getAllocatableBytes` 预检后再传入。

## 第 4 层：可重建的索引与易失缓存

### Android Room

Room 是 SQLite，正是「删行后文件不变小，需要 VACUUM 和临时空间」的那类存储。但 Room 只是索引，可以从 `work_view` 和事件日志重建，所以：

- **不在原地 VACUUM。** 如果膨胀，或者 schema 迁移失败，直接删库重建。重建只需要逐个作品调用一次 `work_view`，不需要额外空间。
- **孤儿的方向和服务器相反。** 在 Android 上文件是真相：
  - Room 里有记录、但作品目录不存在：这条记录是垃圾，删掉。
  - 作品目录存在、但 Room 里没有记录：这不是垃圾，而是待重建的索引项，重新登记。
  - 启动时做一次对账。

**删除作品是两阶段的：**

1. 接头原子写入 `.agent/deleted` 墓碑文件，Room 中这一行标记为删除中；
2. 接头递归删除作品目录；
3. 删除 Room 这一行。

崩溃后对账时：有墓碑的目录继续删完；没有墓碑的目录重新登记。这样不会因为 Room 丢了行就把稿件当成垃圾删掉。

### 内核槽位（`files/core/`）

- 只保留当前活动版本、上一个可用版本和 APK 内置版本，其余槽位内容在切换成功后删除。
- 有进行中或待恢复的回合时，不切换槽位，也不删除槽位。这和第 3 层的锁共用 `docs/android-writing-client.md` 第 8 节的互斥规则。

### Android 上的调度

- `:agent` 进程只在回合进行时以前台服务存在，所以第 3 层回收主要在回合收尾时顺带执行。
- 用户在设置页点「清理」时，壳绑定服务调用 `gc_work`，界面显示「已删 / 候选」进度。
- 不用 `WorkManager` 做周期回收：空闲时拉起 Python 解释器的内存和电量开销，比回收收益大。
- 壳不连接本平台。回收不假设网络，也不读取服务器上的会话或 Work。

## 调度与观测（服务器）

| 任务 | 发起 | 执行 | 周期 | 额外触发 |
|---|---|---|---|---|
| 第 0 层：保留期、删分区、过期行 | api `_lease_reclaim_loop` | api，使用 bypass 连接池 | 每小时 | — |
| 第 1 层：blob 清扫 | api `_lease_reclaim_loop` | api，使用 bypass 连接池 | 每天 | — |
| 第 2 层：Work 回收 | api 入队 `work_gc` | runtime 领取 | 每天 | 删除 Work 或批量删除会话后补排 |

**指标：** `gc_marked`、`gc_candidates`、`gc_deleted`、`gc_aborted{layer,reason}`、`gc_bytes_reclaimed{layer}`。

`gc_aborted` 持续非零时要告警：说明标记阶段反复扫不全，存储只增不减。

本地接头的 `GcReport` 字段与上述指标同名，命令行壳以 JSON 打印，Android 在诊断页展示。

## 落地顺序

1. **本地接头。** 回合台账、打开时对账、作品锁、原子写与落盘顺序、已有对象校验、标记时的版本检查、撤销后回收、`gc_work`、导出的两种模式、暂存目录导入，以及 R6 的三个接头错误。这一步修掉 `revert_turn` 的顺序缺陷，并且是 Android 开工门禁 G4、G5 的前提，优先做。合并门槛是下文「本地接头特有」的测试全部通过。命令行壳先用到；手机装上同一内核即有，不另写一份。
2. **服务器第 0 层。** 补齐删除路径、挂上周期任务、补删除 Work 的路径和墓碑。不等对象回收。
3. **默认值与测量。** `model_envelope_sample_rate` 降到 0.01 量级。测量每 step 的写入字节和抽样重复率，与审计负责人按第 1 层的三档定下 `raw_snapshot_enabled` 和保存形状。
4. **服务器第 2 层。** 先做影子 git 的孤儿提交改造、`gc.auto=0`、撤销接口的共享锁和服务器自己的回退窗口，再做 `work_gc`。`work_gc` 先只标记、只上报候选；下文「服务器第 1、2 层」里影子 git 的并发测试通过之后才打开清扫。
5. **分区迁移。** 按第 0 层的迁移步骤逐表实施，每张表单独一个迁移。本环境不保留旧行：删掉项目 Postgres 的 `agent` 库，建空库，从 `0001_phase0` 升到当前版本。空表上的迁移完成改名和挂载，并在父表插入一行后收到 `turn_events_channel` 上的门铃。不在生产规模的副本上演练。存量膨胀的非分区表用 `pg_repack` 处理；空库没有膨胀的表，不执行 `pg_repack`。
6. **服务器第 1 层。** 仅在第 3 步落到第三档时才做。
7. **Android 壳。** Room 对账、两阶段删除作品、槽位清理，随 `clients/android/` 原型一起实现。回收本身不在壳里再写。

## 测试

标记—清扫的放弃和复活，服务器堆与接头堆各自测自己的根。一边通过不能代替另一边。接头测试放在 `services/runtime/tests/`。

- **扫不全即放弃：** 根源读取失败、清单损坏、遇到高版本 `schema_version`，三种情况都零删除，并给出 `aborted` 原因。
- **复活：** 一个块或对象上一轮已成孤儿，本轮又被引用，断言它不会被删。
- **保留窗口：** 接头侧，第 33 个回合开始后，最早的回合抛 `TurnNotRevertable`；`interrupted` 状态的回合不受影响。服务器侧用它自己的窗口，不断言等于 32。
- **断点续跑：** 回收中途终止后重启，从游标继续，`deleted` 不重复计数。

本地接头特有：

- **撤销顺序：** 用随机的 `uuid4` turn_id 连续跑 5 个回合，撤销第 3 个，断言恰好丢弃第 3 到第 5 个。
- **崩溃留下半截对象：** 在 `rename` 前终止进程，断言没有出现同名的半截对象；`revert_turn` 遇到损坏对象时抛 `SnapshotCorrupt`。
- **已有坏对象：** 预先放一个文件名正确、内容被篡改的同大小对象，再快照同样内容，断言对象被覆盖为正确内容。
- **落盘顺序的每个断点：** 在对象、清单、台账三步之间分别终止，重新打开后断言对账结果与对账表一致，且 `running` 回合变为 `interrupted` 或 `failed`，不被清扫。
- **内核回滚：** 用高版本清单跑低版本回收，断言零删除。
- **导入：** 对象内容与文件名不符、条目含 `../`、条目是符号链接、目标作品已存在，四种 zip 都被拒绝，且目标目录和暂存目录都不存在。

服务器第 0 层：

- **分区唯一约束：** 同一 `(turn_id, sequence)` 插两次仍抛 `UniqueViolationError`，`append_event` 重试成功。
- **跨月 Turn：** 月底开始、次月结束的 Turn，事件全部落在开始月的分区。
- **分区被挂住：** 分区里有非终态 Turn 时不删，`gc_aborted{reason="partition_pinned"}` 计数。
- **触发器：** 分区父表上插入事件仍发出 `NOTIFY`。

服务器第 1、2 层：

- **外键竞争：** 引用插入与清扫并发执行，不留下悬空引用，写入方重试能成功。
- **影子 git 回收：** 删掉窗口外的标签并执行 gc 后对象数下降，窗口内回合的 `restore_turn` 仍然可用。
- **列举之后的新标签：** 在列举与读根之间新建一个回合并写标签，断言它不被删。
- **旧副本移动标签：** 在列举之后对窗口外的标签再做一次 preimage 提交，断言比较并交换删除失败、该标签和它的 `recorded/` 保留，下一轮再删。
- **复活对象：** 新回合写入与窗口外旧对象内容相同的文件，随后立刻压缩，断言新回合的 `restore_turn` 可用。
- **撤销与回收并发：** 撤销持共享锁时 `work_gc` 跳过该 Work；窗口外的撤销不改动工作区。
- **中途退出：** 清扫或压缩中途终止后重跑，回收继续完成，`gc_runs.deleted` 不重复计数。
- **Work 删除：** 有非终态 run 时拒绝；删除后墓碑过宽限，目录被删、墓碑随后删除；没有墓碑的孤立目录不删。
- **会话删除：** 删除后原先漏掉的表里不再残留该会话的行。

Android（随原型）：

- **Room 对账：** 删掉 Room 数据库后重建，作品列表一致。
- **两阶段删除：** 在两个阶段之间杀进程，重启后作品被删完，不会复活。
- **空间不足：** 剩余空间低于阈值时，回合不开始并提示 `storage_low`。
