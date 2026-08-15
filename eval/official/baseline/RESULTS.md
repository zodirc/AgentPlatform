# Official 结果表（可更新）

- **embed 口径**: `bge-m3@1024` / INDEX 12（检索相关行）
- **protocol**: `official-small-2026-08-m3` · L1 agent-path · arm=free · sample_tier=smoke
- **本表更新**: 2026-08-15（`latest_*` → 手填本表；机器指针见 `official-small-2026-08-m3.json` / `SCORECARD.md` 冒烟栏）
- **模型（context / coding）**: `deepseek-v4-flash`（provider=deepseek）

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
