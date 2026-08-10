# SWE-bench Lite L1 · n5 结果纪要（Ops）

记录来源：`TEST.log`（Ops Official Bench 产物面板粘贴）+ 跑次
`d10472fd-548b-4dbe-8299-306f86921a41`（子套件
`309e5ab1-f872-4457-a1f9-c1e56279dd72`）。

日期：2026-08-10（UTC 约 15:57–16:39）。

## 1. 配置摘要

| 项 | 值 |
|----|-----|
| 路径 | L1 agent-path（`scenario_id=agent`） |
| tier | n5（5 题，全 astropy） |
| checkout | 是（`has_repo=true` / `mirror_hit=true`） |
| harness | 开启，但 **exit 1** → 无 `resolve_rate` |
| 写工具 | 已从 agent 白名单移除 `propose_patch`；本跑 patch 来源为 `git_diff` |

## 2. 套件指标（与 TEST.log 一致）

| 指标 | 值 | 含义 |
|------|-----|------|
| `n_instances` | 5 | 题数 |
| `n_nonempty_patches` | 3 | 非空 patch 数 |
| `patch_rate` | 0.60 | 3/5 产出非空 diff（**辅助指标**，≠ 官方 resolve） |
| `harness_error` | `harness exit 1` | 官方 swebench harness 失败，**无 resolve_rate** |

分桶（n=5）：

| bucket | n | 占比 |
|--------|---|------|
| `patch_no_apply` | 3 | 60% |
| `no_patch` | 2 | 40% |

## 3. 逐题

| instance | bucket | source | apply | steps | terminal | 备注 |
|----------|--------|--------|-------|-------|----------|------|
| `astropy__astropy-12907` | `no_patch` | none | — | 12 | failed | 有 `ran_tests`；未留下可提取 diff |
| `astropy__astropy-14182` | `no_patch` | none | — | 57 | failed | 步数触顶附近；无 patch |
| `astropy__astropy-14365` | `patch_no_apply` | git_diff | no | 50 | completed | 有 diff（~1.8k chars）但 `git apply --check` 失败 |
| `astropy__astropy-14995` | `patch_no_apply` | git_diff | no | 50 | completed | 有 diff（~0.7k）不可 apply |
| `astropy__astropy-6938` | `patch_no_apply` | git_diff | no | 50 | completed | 有 diff（~0.6k）不可 apply |

产物侧：`predictions.jsonl` 中 3 条非空、`model_patch` 为 unified-looking diff；2 条空串。

## 4. 结论（效果怎么读）

1. **还不能谈 SWE resolve**：harness 未成功，官方效果分缺失；面板上的 `pass` 仍是「非空 patch」语义。
2. **相对早期 propose_patch 合成假 diff 有进步**：来源已是 `git_diff`（worktree 真实改动），不再是 span 拼出来的伪 patch。
3. **主卡点在「落笔可 apply」**：3 个有 diff 的题全部 `patch_applies=false`。抽查 `predictions.jsonl` 可见 **diff 在行中被截断**（例如 `+    _l`、`elif operand is None or operand.m`、`np.char.replace(...` 未写完）——更像步数打满 / 工具链未提交完整 span，而不是「整洁但语义错」的 patch。
4. **定位/探索仍贵**：两道 `no_patch` 题分别 12 / 57 步失败收场，说明读码与改写闭环仍不稳。
5. **下一步优先序**（相对结构智能双轨）：
   1. 修 harness（exit 1 根因：镜像/数据集过滤/predictions 空行等）→ 拿到 `resolve_rate`；
   2. 结束前强制完整 `git diff` + `git apply --check`；拒收截断 diff；
   3. 再跑 n5 / n25 对照 structural on/off。

## 5. Ops 产物链备注

本跑次触发了报告链接体验问题：浏览器直开 `/api/v1/ops/official/runs/.../report|predictions` **不带 Bearer** → 401；聚合 HTML 嵌套子报告时曾丢掉子 CSS。已改为 Ops UI **带鉴权 fetch + blob 打开/下载**，并加固聚合报告样式。

## 6. 相关路径

- Ops run：`d10472fd-548b-4dbe-8299-306f86921a41`
- 子 coding run：`eval/reports/official/runs/309e5ab1-f872-4457-a1f9-c1e56279dd72/`
- 粘贴源：仓库根目录 `TEST.log`
- 计划锚点：`docs/plan/coding-structural-intelligence.md` §8
