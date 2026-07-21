# Plan suggest shared config

Canonical weights live in **`weights.json`** (docs/26 PS4d).

| 谁读 | 怎么读 |
|------|--------|
| Runtime | `app.controller.plan_suggest` 启动时加载 |
| Web | Vite 别名 `@plan-suggest/weights.json` |
| Eval / tune | `scripts/plan_suggest_eval.py` 读同一份 |

改线上灵敏度：只改 `weights.json` → 重建/重启 **web + runtime**（两端都要吃到新文件）。

正则词表（编号/衔接词等）仍在代码里；**分数、阈值、高风险词、reason 文案、冷却时长**在本 JSON。
