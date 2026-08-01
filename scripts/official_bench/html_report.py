from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def _metric_bars(metrics: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, val in metrics.items():
        if not isinstance(val, (int, float)):
            continue
        pct = max(0.0, min(100.0, float(val) * 100.0 if float(val) <= 1.0 else float(val)))
        # if already percentage-like (>1 and <=100), use as-is
        width = float(val) if float(val) > 1.0 else float(val) * 100.0
        width = max(0.0, min(100.0, width))
        parts.append(
            f"""
            <div class="metric">
              <div class="metric-label"><span>{_esc(key)}</span>
                <strong>{_esc(f"{float(val):.4f}" if isinstance(val, float) else val)}</strong>
              </div>
              <div class="bar"><i style="width:{width:.1f}%"></i></div>
            </div>"""
        )
    return "\n".join(parts) or "<p class='muted'>无数值指标</p>"


def write_html_report(path: Path, manifest: dict[str, Any]) -> None:
    metrics = manifest.get("metrics") or (manifest.get("summary") or {}).get("metrics") or {}
    cases = manifest.get("cases") or []
    logs = manifest.get("logs") or []
    summary = manifest.get("summary") or {}

    case_rows = []
    for c in cases:
        m = c.get("metrics") or {}
        case_rows.append(
            f"<tr>"
            f"<td><code>{_esc(c.get('case_id'))}</code></td>"
            f"<td class='st-{_esc(c.get('status'))}'>{_esc(c.get('status'))}</td>"
            f"<td><pre>{_esc(json.dumps(m, ensure_ascii=False, indent=2)[:800])}</pre></td>"
            f"<td>{_esc(c.get('error') or '—')}</td>"
            f"</tr>"
        )

    log_rows = []
    for item in logs:
        log_rows.append(
            f"<li><time>{_esc(item.get('at'))}</time> "
            f"<span class='kind'>{_esc(item.get('kind'))}</span> "
            f"{_esc(item.get('message'))}</li>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Official Bench · {_esc(manifest.get("title"))}</title>
  <style>
    :root {{
      --bg: #f6f1e8; --ink: #1c1916; --muted: #6b635a; --line: #d9d0c3;
      --ok: #1f6b4a; --fail: #9b2c2c; --accent: #0f4c5c; --card: #fffdf8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: "Iowan Old Style", "Palatino Linotype", Palatino, serif;
      background:
        radial-gradient(1200px 600px at 10% -10%, #e7f0ef 0%, transparent 55%),
        linear-gradient(180deg, #f8f3eb, var(--bg));
      color: var(--ink); line-height: 1.45;
    }}
    main {{ max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
    h1 {{ font-size: 1.75rem; margin: 0 0 .25rem; letter-spacing: -0.02em; }}
    .sub {{ color: var(--muted); margin-bottom: 1.5rem; }}
    .grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); }}
    .card {{
      background: var(--card); border: 1px solid var(--line); border-radius: 12px;
      padding: 1rem 1.1rem; box-shadow: 0 1px 0 rgba(28,25,22,.04);
    }}
    .card strong {{ display: block; font-size: 1.4rem; }}
    .card span {{ color: var(--muted); font-size: .85rem; }}
    .metric {{ margin: .55rem 0; }}
    .metric-label {{ display:flex; justify-content:space-between; font-size:.9rem; margin-bottom:.2rem; }}
    .bar {{ height: 8px; background: #ece4d8; border-radius: 99px; overflow: hidden; }}
    .bar i {{ display:block; height:100%; background: linear-gradient(90deg, var(--accent), #2a9d8f); }}
    table {{ width:100%; border-collapse: collapse; font-size: .92rem; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: .55rem .35rem; vertical-align: top; text-align: left; }}
    pre {{ margin: 0; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; }}
    .st-pass {{ color: var(--ok); font-weight: 700; }}
    .st-fail {{ color: var(--fail); font-weight: 700; }}
    .st-skipped {{ color: var(--muted); }}
    ol.process {{ padding-left: 1.1rem; }}
    ol.process li {{ margin: .35rem 0; }}
    ol.process time {{ color: var(--muted); font-size: .8rem; margin-right: .4rem; }}
    .kind {{
      display:inline-block; font-size:.7rem; text-transform:uppercase; letter-spacing:.04em;
      border:1px solid var(--line); border-radius: 999px; padding: .05rem .4rem; margin-right:.35rem;
      color: var(--accent);
    }}
    .muted {{ color: var(--muted); }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85em; }}
  </style>
</head>
<body>
<main>
  <h1>{_esc(manifest.get("title") or "Official Bench")}</h1>
  <p class="sub">
    suite=<code>{_esc(manifest.get("official_suite"))}</code> ·
    id=<code>{_esc(manifest.get("id"))}</code> ·
    status=<strong>{_esc(manifest.get("status"))}</strong><br/>
    {_esc(manifest.get("created_at"))} → {_esc(manifest.get("finished_at"))}
  </p>

  <div class="grid">
    <div class="card"><span>Cases</span><strong>{_esc(summary.get("total", 0))}</strong></div>
    <div class="card"><span>Pass</span><strong>{_esc(summary.get("pass", 0))}</strong></div>
    <div class="card"><span>Fail</span><strong>{_esc(summary.get("fail", 0))}</strong></div>
    <div class="card"><span>Skipped</span><strong>{_esc(summary.get("skipped", 0))}</strong></div>
  </div>

  <section class="card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">指标</h2>
    {_metric_bars(metrics if isinstance(metrics, dict) else {})}
  </section>

  <section class="card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">用例结果</h2>
    <table>
      <thead><tr><th>Case</th><th>Status</th><th>Metrics</th><th>Error</th></tr></thead>
      <tbody>{"".join(case_rows) or "<tr><td colspan=4 class='muted'>无用例</td></tr>"}</tbody>
    </table>
  </section>

  <section class="card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">过程日志</h2>
    <ol class="process">{"".join(log_rows) or "<li class='muted'>无日志</li>"}</ol>
  </section>
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
