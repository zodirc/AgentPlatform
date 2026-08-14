# Official 结果表（可更新）

- **embed 口径**: `bge-m3@1024` / INDEX 12（检索相关行）
- **protocol**: `official-small-2026-08-m3` · L1 agent-path · arm=free · sample_tier=smoke

## retrieval · BEIR

| 字段 | 值 |
|------|----|
| run_id | `cd16092c-5b35-478b-ba1f-4bbada5876b4` |
| date | 2026-08-07 |
| embed | bge-m3@1024 / INDEX 12 |
| n_queries | 20 |
| n_qrels | — |
| n_scored | — |
| infra_rate | — |
| n_infra_excluded | — |
| ndcg_at_1 | — |
| ndcg_at_10 | 0.4755 |
| ndcg_at_100 | — |
| recall_at_1 | — |
| recall_at_10 | 0.4908 |
| recall_at_100 | — |
| map_at_1 | 0.246 |
| map_at_10 | — |
| map_at_100 | — |
| ndcg_at_1_incl_infra | — |
| ndcg_at_10_incl_infra | — |
| ndcg_at_100_incl_infra | — |
| recall_at_1_incl_infra | — |
| recall_at_10_incl_infra | — |
| recall_at_100_incl_infra | — |
| map_at_1_incl_infra | — |
| map_at_10_incl_infra | — |
| map_at_100_incl_infra | — |

## retrieval_zh · C-MTEB

| 字段 | 值 |
|------|----|
| run_id | `f84fd420-9fba-4f43-8e81-618ce0e2d7d3` |
| date | 2026-08-07 |
| embed | bge-m3@1024 / INDEX 12 |
| n_queries | — |
| n_qrels | — |
| n_scored | — |
| infra_rate | 0 |
| n_infra_excluded | — |
| ndcg_at_1 | — |
| ndcg_at_10 | 0.6780 |
| ndcg_at_100 | — |
| recall_at_1 | — |
| recall_at_10 | 0.8667 |
| recall_at_100 | — |
| map_at_1 | 0.517 |
| map_at_10 | — |
| map_at_100 | — |
| ndcg_at_1_incl_infra | — |
| ndcg_at_10_incl_infra | — |
| ndcg_at_100_incl_infra | — |
| recall_at_1_incl_infra | — |
| recall_at_10_incl_infra | — |
| recall_at_100_incl_infra | — |
| map_at_1_incl_infra | — |
| map_at_10_incl_infra | — |
| map_at_100_incl_infra | — |

## context · LongBench

| 字段 | 值 |
|------|----|
| run_id | `b9bcf931-9a7d-4528-af8b-bc5506be6955` |
| date | 2026-08-07 |
| model | deepseek-v4-flash |
| scorer | v2 |
| agent_f1 | 0.5288 |
| agent_em | 0.2500 |
| agent_f1_incl_infra | — |
| agent_em_incl_infra | — |
| agent_f1_scorer | — |
| n_cases | — |
| n_scored | — |
| n_infra_excluded | — |
| infra_rate | — |

## coding · SWE-bench Lite n5 + harness

| 字段 | 值 |
|------|----|
| run_id | `5a4e9ba9-c3d2-4df6-bf0c-39e87d891826` |
| ops_run_id | `05bb784b-b86c-4768-b011-3ea527090a49` |
| date | 2026-08-14 |
| model | deepseek-v4-flash |
| coding_tier | n5 |
| harness | yes |
| sample_tier | smoke |
| n_instances | 5 |
| n_instance_ids | 5 |
| n_nonempty_patches | 5 |
| patch_rate | 1.0 |
| resolve_rate | 0.6 |
| n_resolved | 3 |
| exit_code | 0 |
| harness_run_id | agentplatform-20260814082644 |
| harness_child | `3b5d555d-410f-4efd-a78e-7269be578c96` |
| locate_fuse_ok_rate | 0.16666666666666666 |
| locate_fuse_n | 18 |
| n_locate_fuse_no_ws_symbol | 11 |
| n_locate_fuse_definition_null | 6 |
| n_locate_fuse_lsp_failed | 0 |
| n_locate_fuse_lsp_timeout | 0 |
| n_grep_locate_failed | 0 |
| n_grep_locate_incomplete | 15 |
| edit_impact_coverage | 1.0 |
| edit_checks_coverage | 1.0 |
| edit_related_tests_coverage | 0.22727272727272727 |
| edit_ok_n | 22 |
| syntax_reject_count | 0 |
| syntax_warning_passthrough_count | 0 |
| span_fail_n | 1 |
| bucket_share_no_patch | 0.0 |
| bucket_share_patch_no_apply | 0.0 |
| file_hit_rate | 1.0 |
| file_hit_n | 5 |
| repro_rerun_rate | 0.2 |
| tests_before_submit_rate | 1.0 |
| read_outline_coverage | 0.94 |
| n_read_truncated | 50 |
| n_read_with_outline | 47 |
| test_summary_attach_rate | 0.0 |
| n_testish_tool | 55 |
| n_test_summary | 0 |
| related_tests_adoption_rate | 0.5 |
| verify_receipt_rate | 0.6 |
| verify_receipt_then_test_rate | 1.0 |
| n_verify_receipt | 3 |
| resolved_ids | astropy-12907, astropy-14995, astropy-6938 |
| unresolved_ids | astropy-14182, astropy-14365 |

> 对照上一烟 `66077649`（Wave 3 后）：resolve 同为 **0.6 / 同未过两题**。本跑为 **Wave 4 后首趟 n5 冒烟**（`tests_before_submit=1.0` 为 testish 指纹，`test_summary` 附带 0/55；14182 `turn.failed` PG timeout，勿与「改完仍没过」混桶）。**不作效果结论**。详见 `docs/plan/coding-structural-intelligence.md` §6.7.11。
