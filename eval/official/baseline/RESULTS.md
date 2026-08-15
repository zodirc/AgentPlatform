# Official 结果表（可更新）

- **embed 口径**: `bge-m3@1024` / 下方第1轮主表 = INDEX **12** 锚点；第2轮检索按 INDEX **13**
- **protocol**: `official-small-2026-08-m3` · L1 agent-path · arm=free · sample_tier=smoke
- **本表更新**: 2026-08-15 17:12 CST（第2轮 · quality-uplift 四套件齐）
- **轮次**: 第1轮 2026-08-15 12:14–13:01 CST · INDEX 12；第2轮 2026-08-15 17:12 CST 入账 · INDEX 13
- **模型（context / coding）**: `deepseek-v4-flash`（provider=deepseek）

---

## 第2轮 · quality-uplift（2026-08-15 17:12 CST 入账 · INDEX 13）

对照第1轮（2026-08-15 12:14–13:01 CST · INDEX **12**）。smoke 口径 **不作效果结论、不升 SCORECARD 主栏**。子跑：

| 套件 | run_id |
|------|--------|
| coding | `6926b961-4054-485c-b86c-5fe6f2e50e63` |
| retrieval_zh | `4ddcfcfd-dd7c-4e2a-a86c-563a94111869` |
| retrieval（BEIR） | `8c76c027-1bb5-4dc7-b540-7ce595c4acbf` |
| context | `1029a918-773c-45c5-a414-60076161a5df` |

### coding · SWE-bench Lite n5 + harness

通过仍是 **12907 / 14995 / 6938**；未过仍是 **14182 / 14365**（与第1轮同题）。

| 字段 | 第1轮 INDEX12 | 第2轮 | Δ |
|------|-------------|------|---|
| resolve / n_resolved | 0.6 / 3 | **0.6 / 3** | 0 |
| patch_rate / file_hit | 1.0 / 1.0 | 1.0 / 1.0 | 0 |
| steps_total | 467 | **269** | −42% |
| elapsed_s_total | 6927.7 | **4027.5** | −42% |
| suite_wall_s | — | **2308.6**（第2轮墙钟） | 题内合计 67.1m → 有并行 |
| fuse_ok（n=12） | 0.417 | **0.583** | +0.17 |
| no_ws_symbol | 9 | 6 | −3 |
| non_definition | — | 0 | C-6 未进桶 |
| related_tests cov | 0.222 | **0.556** | **过 C-4 ≥0.5** |
| related_tests adoption | 0.75 | 0.60 | −0.15 |
| test_summary | 0/50 | **5/23（0.217）** | **<0.6** |
| n_testish / edit_ok_n | 50 / 27 | 23 / 9 | 试测与写入腰斩 |
| tests_before_submit | 1.0 | 1.0 | 0 |
| verify_receipt | 0.8 | 0.6 | −0.2 |
| outline | 1.0（28/28） | 0.967（29/30） | −1 窗 |
| span_fail_n | 0 | 1 | +1 |
| repro_rerun | 0.4 | 0 | 不再复跑 |
| run_id | `ff37ceb5-…` | `6926b961-…` | |

#### 按题

| instance | 第1轮 steps / s | 第2轮 steps / s | harness |
|----------|----------------:|----------------:|---------|
| astropy-12907 | 113 / 1180 | **43 / 389** | resolved → resolved |
| astropy-14995 | 32 / 292 | 49 / 696 | resolved → resolved（本题变慢） |
| astropy-6938 | 36 / 371 | 47 / 488 | resolved → resolved（本题略慢） |
| astropy-14182 | 150 / 2623 | **55 / 1465** | unresolved → unresolved |
| astropy-14365 | 136 / 2461 | **75 / 990** | unresolved → unresolved |

### retrieval_zh · C-MTEB（n=20/集 · 3 集 · infra=0）

分桶（n=60 query）：ok 33（55%）· weak_hits 19（32%）· query_drift 4 · no_search 3 · search_cap 1。median nDCG=1.000（中位极易饱和，宏分看下表）。

| 字段 | 第1轮 INDEX12 | 第2轮 | Δ |
|------|-------------|------|---|
| ndcg_at_1 | 0.5000 | **0.6000** | +0.10 |
| ndcg_at_10 | 0.6433 | **0.6963** | +0.053 |
| ndcg_at_100 | 0.6475 | 0.7038 | +0.056 |
| recall_at_10 | 0.8167 | **0.8167** | 0 |
| recall_at_100 | 0.8333 | **0.8500** | +0.017 |
| map_at_10 | 0.5892 | **0.6588** | +0.070 |
| n_queries / n_qrels | 20 / — | 20 / 983 | 同档 |
| suite_wall_s | — | 713.9 | 第2轮墙钟 |
| run_id | `de6ae46c-…` | `4ddcfcfd-…` | |

### retrieval · BEIR（n=20/集 · 3 集 · INDEX 13 · **第一验收位**）

分桶（n=60）：ok 26（43%）· weak_hits 23（38%）· search_cap 4 · query_drift 4 · no_search 3。median nDCG=0.379。

| 字段 | 第1轮 INDEX12 | 第2轮 | Δ |
|------|-------------|------|---|
| ndcg_at_1 | 0.3944 | **0.4333** | +0.039 |
| ndcg_at_10 | 0.4547 | **0.4508** | **−0.004** |
| ndcg_at_100 | 0.4298 | 0.4179 | −0.012 |
| recall_at_1 | 0.2460 | 0.2469 | 0 |
| recall_at_10 | 0.4571 | **0.4327** | **−0.024** |
| recall_at_100 | 0.5296 | **0.4954** | **−0.034**（方案第一位：**未升反降**） |
| map_at_10 | 0.3149 | 0.3047 | −0.010 |
| map_at_100 | 0.3244 | 0.3132 | −0.011 |
| n_queries / n_qrels | 20 / — | 20 / 423.7 | 宏均 qrels |
| run_id | `c44a9f00-…` | `8c76c027-…` | |

### context · LongBench（n=60 · scorer v2 · limit=20/task）

分桶：ok 46（77%）· verbose_answer 6（10%）· wrong_answer_after_read 6（10%）· truly_abandoned 2（3%）。**EM 全 60 题为 0。**

| 字段 | 第1轮 INDEX12 | 第2轮 | Δ |
|------|-------------|------|---|
| agent_f1 | 0.5579 | **0.4557** | **−0.102** |
| agent_em | 0.3000 | **0.0000** | **−0.30** |
| n_cases / n_scored | 60 / 60 | 60 / 60 | 0 |
| infra | 0 | 0 | 0 |
| run_id | `4d090bc1-…` | `1029a918-…` | |

### 全程归因（方向，不作效果结论）

**编码** — 与第2轮前半（coding + retrieval_zh）判断一致，现有题表补全。resolve 钉死同题 3/5。C-4 过线；C-1 0.217 未过 0.6。步数降主要来自两道未过题（14182/14365 约腰斩）和 12907；两道本就会过的题（14995/6938）反而更慢。执行环变薄没有改 F2P 结果。

**中文检索** — R@10 持平、排序抬升，符合「CJK 下 R-1 截断本就不重、面包屑改排序」的预期。no_search 3/60（5%）把若干题直接打成 0。

**BEIR（R-1 真验收，本档未过）** — 英文本应最吃 token 对齐，结果 **R@100 0.530→0.495、R@10 0.457→0.433**。nDCG@1 却 +3.9pt：顶一更准，召回池变窄。n=20 噪声大，但不能把 INDEX 13 说成召回修复。假设待证：450 token 碎片变多、top-k 覆盖不到金标所在的新 chunk；或标题/面包屑改了 BM25 面。R-5 rerank 方案明确写了「召回不抬则不开」。no_search 同样 3 题。

**上下文（X 线本表数字被口径污染）** — 当时 v2 EM 是规范化后的整句相等、**不抽 `Answer:`**。X-3 prompt 强制 `Answer: <phrase>` 后，`answer berlin` 对 gold `berlin` → **EM 必 0**，F1 被前缀稀释。60 题 EM=0、F1 仍 0.46 同向，是统计问题不是阅读归零。verbose_answer 仍 6 题（narrative 最长 252 字），抽取救不了没写 `Answer:` 行的长文。X-1/X-2 是否改善导航，不能用本表判。**scorer 已改为预测侧抽末行 `Answer:`（金标不动）；本表 0.00 / 0.4557 不回溯改写，下次 context 套件才用新口径。**

**下一步（仍 smoke）**

1. Context：用新 scorer 复跑（或对 `1029a918-…` 产物离线重打）再看 F1/EM；不把第2轮 0.00 当效果。
2. BEIR：n≥100 再判 R-1；先查 no_search + chunk 质检（硬切率 / 超 512 token 占比）。
3. C-1 继续抠 test_summary（管道/截断）。
4. 不升主栏。

---

以下为 **第1轮 · INDEX 12**（2026-08-15 12:14–13:01 CST）锚点主表（未覆盖）。

## retrieval · BEIR

| 字段 | 值 |
|------|----|
| run_id | `c44a9f00-c926-4b34-a34c-f2e1fa37a1a2` |
| date | 2026-08-15 |
| embed | bge-m3@1024 / INDEX 12 |
| n_queries | 20 |
| n_qrels | — |
| n_scored | 20 |
| infra_rate | 0 |
| n_infra_excluded | 0 |
| ndcg_at_1 | 0.3944 |
| ndcg_at_10 | 0.4547 |
| ndcg_at_100 | 0.4298 |
| recall_at_1 | 0.2460 |
| recall_at_10 | 0.4571 |
| recall_at_100 | 0.5296 |
| map_at_1 | 0.2460 |
| map_at_10 | 0.3149 |
| map_at_100 | 0.3244 |
| ndcg_at_1_incl_infra | 0.3944 |
| ndcg_at_10_incl_infra | 0.4547 |
| ndcg_at_100_incl_infra | 0.4298 |
| recall_at_1_incl_infra | 0.2460 |
| recall_at_10_incl_infra | 0.4571 |
| recall_at_100_incl_infra | 0.5296 |
| map_at_1_incl_infra | 0.2460 |
| map_at_10_incl_infra | 0.3149 |
| map_at_100_incl_infra | 0.3244 |

## retrieval_zh · C-MTEB

| 字段 | 值 |
|------|----|
| run_id | `de6ae46c-029b-4639-a865-2c2f5b455d86` |
| date | 2026-08-15 |
| embed | bge-m3@1024 / INDEX 12 |
| n_queries | 20 |
| n_qrels | — |
| n_scored | 20 |
| infra_rate | 0 |
| n_infra_excluded | 0 |
| ndcg_at_1 | 0.5000 |
| ndcg_at_10 | 0.6433 |
| ndcg_at_100 | 0.6475 |
| recall_at_1 | 0.5000 |
| recall_at_10 | 0.8167 |
| recall_at_100 | 0.8333 |
| map_at_1 | 0.5000 |
| map_at_10 | 0.5892 |
| map_at_100 | 0.5903 |
| ndcg_at_1_incl_infra | 0.5000 |
| ndcg_at_10_incl_infra | 0.6433 |
| ndcg_at_100_incl_infra | 0.6475 |
| recall_at_1_incl_infra | 0.5000 |
| recall_at_10_incl_infra | 0.8167 |
| recall_at_100_incl_infra | 0.8333 |
| map_at_1_incl_infra | 0.5000 |
| map_at_10_incl_infra | 0.5892 |
| map_at_100_incl_infra | 0.5903 |

> 机器 `baseline --update` 当前未写入 `retrieval_zh` 冒烟栏（suite id 映射为 unknown）；本表仍按 `latest_retrieval_zh.json` 完整记录。**勿与 BEIR 混宏分**。

## context · LongBench

| 字段 | 值 |
|------|----|
| run_id | `4d090bc1-b0fd-41ad-9b4f-d9ab702653ac` |
| date | 2026-08-15 |
| model | deepseek-v4-flash |
| scorer | v2 |
| agent_f1 | 0.5579 |
| agent_em | 0.3000 |
| agent_f1_incl_infra | 0.5579 |
| agent_em_incl_infra | 0.3000 |
| agent_f1_scorer | 2 |
| n_cases | 60 |
| n_scored | 60 |
| n_infra_excluded | 0 |
| infra_rate | 0 |

## coding · SWE-bench Lite n5 + harness

| 字段 | 值 |
|------|----|
| run_id | `ff37ceb5-c15a-4b34-9646-8105f964e222` |
| harness_child | `1a9244ba-f07d-4cd9-b956-87f5248180fa` |
| date | 2026-08-15 |
| model | deepseek-v4-flash |
| coding_tier | n5 |
| harness | yes |
| sample_tier | smoke |
| workspace_index | true |
| workspace_index_wait_ready | true |
| n_instances | 5 |
| n_instance_ids | 5 |
| n_nonempty_patches | 5 |
| patch_rate | 1.0 |
| resolve_rate | 0.6 |
| n_resolved | 3 |
| exit_code | 0 |
| harness_run_id | agentplatform-20260815040631 |
| steps_total | 467 |
| elapsed_s_total | 6927.7 |
| locate_fuse_ok_rate | 0.4166666666666667 |
| locate_fuse_n | 12 |
| n_locate_fuse_no_ws_symbol | 9 |
| n_locate_fuse_definition_null | 0 |
| n_locate_fuse_lsp_failed | 0 |
| n_locate_fuse_lsp_timeout | 0 |
| n_grep_locate_failed | 0 |
| n_grep_locate_incomplete | 7 |
| edit_impact_coverage | 1.0 |
| edit_checks_coverage | 1.0 |
| edit_related_tests_coverage | 0.2222222222222222 |
| edit_ok_n | 27 |
| syntax_reject_count | 0 |
| syntax_warning_passthrough_count | 0 |
| span_fail_n | 0 |
| bucket_share_no_patch | 0.0 |
| bucket_share_patch_no_apply | 0.0 |
| file_hit_rate | 1.0 |
| file_hit_n | 5 |
| repro_rerun_rate | 0.4 |
| tests_before_submit_rate | 1.0 |
| read_outline_coverage | 1.0 |
| n_read_truncated | 28 |
| n_read_with_outline | 28 |
| test_summary_attach_rate | 0.0 |
| n_testish_tool | 50 |
| n_test_summary | 0 |
| related_tests_adoption_rate | 0.75 |
| verify_receipt_rate | 0.8 |
| verify_receipt_then_test_rate | 1.0 |
| n_verify_receipt | 4 |
| resolved_ids | astropy-12907, astropy-14995, astropy-6938 |
| unresolved_ids | astropy-14182, astropy-14365 |

### coding · 按题（infer 墙钟 / 步数 / harness）

| instance | patch | steps | elapsed_s | harness | bucket |
|----------|-------|------:|----------:|---------|--------|
| astropy__astropy-12907 | git_diff | 113 | 1180.3 | resolved | ok |
| astropy__astropy-14182 | git_diff | 150 | 2623.0 | unresolved | patch_not_resolved |
| astropy__astropy-14995 | git_diff | 32 | 292.2 | resolved | ok |
| astropy__astropy-6938 | git_diff | 36 | 371.1 | resolved | ok |
| astropy__astropy-14365 | git_diff | 136 | 2461.1 | unresolved | patch_not_resolved |

> 对照上一烟 `5a4e9ba9`（2026-08-14 Wave 4）：resolve 同为 **0.6 / 同未过两题（14182、14365）**。本跑开启 **`workspace_index_wait_ready=true`**（先 AST 再开题）；Locate `fuse_ok≈0.42`（先前烟约 0.17），`definition_null=0`。**steps_total=467 · elapsed≈1.92h**（五题墙钟合计）。**不作效果结论**（smoke）。详见 `docs/plan/coding-structural-intelligence.md`。
