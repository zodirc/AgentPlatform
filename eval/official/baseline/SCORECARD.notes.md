# SCORECARD 手记附录（生成器保留区）

> 本文件由 `scripts/official_bench/baseline.py` 在生成 [`SCORECARD.md`](SCORECARD.md) 时**原样拼接**到文末「手记附录」段。  
> **改手记只改本文件**；不要手改 `SCORECARD.md` 主表（会被 `--update` / `--write-scorecard` / `--promote-run` 覆盖）。

## Embed / INDEX

- **embed**: `make resolve-embedding` → GPU **`BAAI/bge-m3@1024`**（第1轮 INDEX **12** · `max_seq=512` · 2026-08-15 12:14–13:01 CST；第2轮检索按 INDEX **13** · 2026-08-15 17:12 CST 入账对照）；CPU **`gte-small@384`**。
- Ops 仅分图：BEIR → `retrieval_ops` · C-MTEB → `retrieval_ops_zh`（同模同维，独立 HNSW）。
- 扁平镜像可落根目录 `TEST.log`（可选；不进 git）。

## 冒烟手记（补充 JSON 指针 · 不作效果结论）

机器栏（`smoke_suites`）只保留最近一次 `update-baseline` 写入的指针；下列为调优过程手记，**不可跨模直接比**：

| 套件 | 主指标 | 值 | run_id | 备注 |
|------|--------|----|--------|------|
| retrieval | agent nDCG@10 | **0.4547** | `c44a9f00-c926-4b34-a34c-f2e1fa37a1a2` | 2026-08-15 12:44 CST · **第1轮** · INDEX **12** · BEIR 20q · R@10 **0.4571** · R@100 **0.5296** |
| retrieval_zh | agent nDCG@10 | **0.6433** | `de6ae46c-029b-4639-a865-2c2f5b455d86` | 2026-08-15 · **第1轮** · INDEX **12** · C-MTEB · R@10 **0.8167** · MAP@1 **0.500** · **勿与 BEIR 混宏分** |
| context | agent F1 / EM | **0.5579 / 0.3000** | `4d090bc1-b0fd-41ad-9b4f-d9ab702653ac` | 2026-08-15 13:01 CST · **第1轮** · n=60 · scorer=v2 |
| coding（烟） | resolve_rate | **0.600** | `ff37ceb5-c15a-4b34-9646-8105f964e222` | 2026-08-15 12:14 CST · **第1轮** · n5+harness · **3/5** · stepsΣ **467** · fuse_ok≈**0.42** · test_summary **0** · **非锚点** |
| retrieval（烟·升 INDEX13） | nDCG@10 | **0.4508** | `8c76c027-1bb5-4dc7-b540-7ce595c4acbf` | 2026-08-15 17:12 CST 入账 · **第2轮** · quality-uplift · BEIR 20q · R@10 **0.4327**（−0.024）· R@100 **0.4954**（−0.034，第一验收位未过）· nDCG@1 **0.4333**（+0.039）· **非锚点** |
| retrieval_zh（烟·升 INDEX13） | nDCG@10 | **0.6963** | `4ddcfcfd-dd7c-4e2a-a86c-563a94111869` | 2026-08-15 17:12 CST 入账 · **第2轮** · C-MTEB 20q · R@10 **0.8167**（平）· R@100 **0.8500** · MAP@10 **0.6588** · **勿与 BEIR 混宏分** |
| context（烟·升） | agent F1 / EM | **0.4557 / 0.0000** | `1029a918-773c-45c5-a414-60076161a5df` | 2026-08-15 17:12 CST 入账 · **第2轮** · n=60 · **EM 0 为未抽 `Answer:` 的口径缺口**（scorer 已修、本行不回溯）· **非锚点** |
| coding（烟·升） | resolve_rate | **0.600** | `6926b961-4054-485c-b86c-5fe6f2e50e63` | 2026-08-15 17:12 CST 入账 · **第2轮** · **同题 3/5**（未过 14182/14365）· stepsΣ **269**（−42%）· test_summary **0.217** · related_tests **0.556** · **非锚点** |
| retrieval（史） | agent nDCG@10 | **0.4755** | `cd16092c-5b35-478b-ba1f-4bbada5876b4` | 2026-08-07 · bge-m3 · BEIR 20q · R@10 0.4908 · MAP@1 0.246 |
| retrieval_zh（史） | agent nDCG@10 | **0.6780** | `f84fd420-9fba-4f43-8e81-618ce0e2d7d3` | 2026-08-07 · C-MTEB · R@10 0.8667 · MAP@1 0.517 |
| context（史） | agent F1 / EM | **0.5288 / 0.2500** | `b9bcf931-9a7d-4528-af8b-bc5506be6955` | 2026-08-07 · scorer=v2 |
| retrieval（史） | agent nDCG@10 | **0.5435** | `d31375a5-6884-4007-9bdb-a0d1d65b6d9d` | 2026-08-06 · **gte-large 历史** · smoke · free · 换代前对照 |
| context（史） | agent F1 / EM | **0.5393 / 0.2333** | `46df8722-f2c3-4cc6-8ad5-58efc21d974e` | 2026-08-06 · gte-large 同期 · scorer=v2 |
| retrieval（史） | agent nDCG@10 | 0.4425 | `307ea1d0-6502-468b-85ea-c209f1377567` | 更旧 smoke；保留对照 |
| context（史） | agent F1 / EM | 0.3677 / 0.2500 | `9998d9eb-9973-4938-bacf-3207aca4f781` | 旧 smoke（v1 口径附近）；保留对照 |
| coding（烟·史） | resolve_rate | **0.600** | `5a4e9ba9-c3d2-4df6-bf0c-39e87d891826` | 2026-08-14 · Wave 4 后 · 3/5 同题 · Ops `05bb784b…` |
| coding（烟·史） | resolve_rate | **0.600** | `66077649-7e89-491c-9a9f-010c69aa18d5` | 2026-08-14 · Wave 3 后 · 3/5 同题 |
| coding（烟·史） | resolve_rate | **0.600** | `b3357dd6-19d5-4669-ae06-ec3bc1a50d27` | 2026-08-13 · Wave 3 前对照 |

## 复跑触发条件（锚点落章后）

下列任一发生 → 复跑受影响套件并 `make official-bench-promote-run RUN_ID=…` 刷新主栏：

1. 模型 / 温度 / seed 变更  
2. `system.md` 或 L1 coding prompt 实质变更  
3. 结构车道行为变更（Locate/Impact/Verify / Wave 落地）  
4. embed / INDEX 换代（retrieval）  
5. `protocol_version` 升版  

## 升锚用法

```bash
# 负例：n5 smoke 必须被拒绝
make official-bench-promote-run RUN_ID=b3357dd6-19d5-4669-ae06-ec3bc1a50d27

# 正例：锚点档跑完后（context limit=0 / retrieval 全量 / coding n25+harness）
make official-bench-promote-run RUN_ID=<anchor-run-uuid>
make official-bench-compare
git add eval/official/baseline/
```
