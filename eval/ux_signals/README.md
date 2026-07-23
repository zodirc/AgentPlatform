# UX experience signals (docs/28 PX1)

离线聚合用户行为指标（拒稿 / 短窗再改 / 取消）。**不进** Agent Turn 热路径。

```bash
make ux-signals                          # 内置 spike 自检（须告警）
python3 scripts/ux_signals.py --input eval/ux_signals/fixtures/sample_day.json
python3 -m pytest scripts/tests/test_ux_signals.py -q
```

报告写入 `eval/reports/ux_signals/daily_YYYY-MM-DD.json`（仅计数与比率，无正文）。

Web 只读页：设置 → **体验信号**（`/settings/signals`）→ `GET /api/v1/admin/ux-signals`。
