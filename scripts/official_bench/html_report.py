from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


_STATUS_ZH = {
    "pass": "通过",
    "fail": "失败",
    "failed": "失败",
    "skipped": "跳过",
    "pending": "待处理",
    "completed": "已完成",
    "running": "进行中",
    "cancelled": "已取消",
    "canceled": "已取消",
    "queued": "排队中",
    "error": "错误",
    "ok": "正常",
}

_KIND_ZH = {
    "run_started": "开始",
    "run_finished": "结束",
    "case_finished": "用例结束",
    "log": "日志",
    "phase": "阶段",
    "l2_probe": "L2 探针",
    "error": "错误",
    "warn": "警告",
    "warning": "警告",
    "metric": "指标",
}

_METRIC_ZH = {
    "ndcg_at_5": "nDCG@5",
    "ndcg_at_10": "nDCG@10",
    "ndcg_at_20": "nDCG@20",
    "recall_at_5": "召回@5",
    "recall_at_10": "召回@10",
    "recall_at_20": "召回@20",
    "map_at_5": "MAP@5",
    "map_at_10": "MAP@10",
    "map_at_20": "MAP@20",
    "agent_f1": "Agent F1",
    "f1": "F1",
    "patch_rate": "补丁产出率",
    "resolve_rate": "官方解决率",
    "n_instances": "实例数",
    "n_instance_ids": "实例 ID 数",
    "n_nonempty_patches": "非空补丁数",
    "n_resolved": "已解决数",
    "exit_code": "退出码",
    "harness_run_id": "Harness 运行 ID",
    "harness_log": "Harness 日志",
    "edit_ok_n": "编辑成功数",
    "edit_checks_coverage": "编辑校验覆盖",
    "edit_impact_coverage": "编辑影响覆盖",
    "locate_fuse_ok_rate": "定位融合成功率",
    "locate_fuse_n": "定位融合次数",
    "file_hit_rate": "文件命中率",
    "file_hit_n": "文件命中计分题数",
    "repro_rerun_rate": "复现复跑率",
    "tests_before_submit_rate": "交卷前测过率",
    "read_outline_coverage": "截断读大纲覆盖",
    "edit_related_tests_coverage": "相关测试附带覆盖",
}

_SUITE_ZH = {
    "retrieval": "检索（BEIR）",
    "retrieval_zh": "中文检索（C-MTEB）",
    "cmteb": "中文检索（C-MTEB）",
    "context": "上下文（LongBench）",
    "coding": "编码（SWE-bench Lite）",
    "coding_pull": "编码题集拉取",
    "coding_infer": "编码推理",
    "pull": "数据集拉取",
    "p1_lexical_micro": "P1 词面微测",
    "official": "官方评测",
}


def status_zh(status: Any) -> str:
    key = str(status or "").strip().lower()
    return _STATUS_ZH.get(key, str(status or "—"))


def kind_zh(kind: Any) -> str:
    key = str(kind or "").strip().lower()
    return _KIND_ZH.get(key, str(kind or "日志"))


def metric_label(key: str) -> str:
    return _METRIC_ZH.get(key, key)


def suite_zh(suite: Any) -> str:
    key = str(suite or "").strip().lower()
    return _SUITE_ZH.get(key, str(suite or "未知套件"))


def _eval_path_label(eval_path: Any) -> str:
    ep = str(eval_path or "").strip().lower()
    if ep in {"agent", "l1"}:
        return "L1 产品 Turn（主路径）"
    if ep in {"component", "bench", "l0"}:
        return "L0 组件旁路"
    if ep:
        return str(eval_path)
    return "未标注路径"


def flow_steps_for_suite(
    suite: str,
    *,
    eval_path: str | None = None,
    context_dry: bool | None = None,
    coding_harness: bool | None = None,
) -> list[tuple[str, str]]:
    """Return ordered (title, detail) steps describing this run's evaluation flow."""
    s = (suite or "").strip().lower()
    ep = (eval_path or "").strip().lower()
    l1 = ep in {"", "agent", "l1"}

    if s in {"pull"}:
        return [
            ("拉取数据集", "BEIR / LongBench / SWE 等（本地已有则跳过）"),
            ("完成", "仅准备数据，不跑打分"),
        ]
    if s in {"coding_pull"}:
        return [
            ("拉取 SWE-bench Lite", "题集与镜像缓存（可跳过）"),
            ("完成", "不进行推理与 harness"),
        ]
    if s in {"p1_lexical_micro"}:
        return [
            ("词面对照", "SciFact：Postgres ts_rank vs Okapi"),
            ("汇总指标", "无需同步语料 / 不调模型"),
            ("生成报告", "写入 report.html"),
        ]
    if s in {"retrieval", "retrieval_zh", "cmteb"}:
        corpus = {
            "retrieval": "BEIR 小量",
            "retrieval_zh": "C-MTEB 小量",
            "cmteb": "C-MTEB 小量",
        }.get(s, "检索语料")
        if l1:
            return [
                ("拉取数据集", f"{corpus}（已缓存则跳过）"),
                ("产品 Turn 检索", "经 search_sources / 主向量指数发问"),
                ("计算检索指标", "nDCG@k · Recall@k · MAP@k（宏平均）"),
                ("落盘与报告", "manifest + report.html；可与基线对比 Δ"),
            ]
        return [
            ("拉取数据集", f"{corpus}（已缓存则跳过）"),
            ("组件检索对照", "hybrid 与 BM25 旁路打分"),
            ("计算 IR 指标", "nDCG@k · Recall@k · MAP@k"),
            ("落盘与报告", "manifest + report.html"),
        ]
    if s in {"context"}:
        if context_dry:
            return [
                ("拉取 LongBench", "小量切片（可缓存）"),
                ("管道冒烟", "dry 模式：不调模型，只验证落盘与流程"),
                ("生成报告", "不作效果结论"),
            ]
        if l1:
            return [
                ("拉取 LongBench", "小量切片（可缓存）"),
                ("产品 Turn 作答", "read_file / search_sources 主路径"),
                ("计算 F1", "对照标准答案打 Agent F1"),
                ("落盘与报告", "manifest + report.html"),
            ]
        return [
            ("拉取 LongBench", "小量切片（可缓存）"),
            ("双臂/三臂评分", "full / truncate / compact 旁路"),
            ("汇总 F1", "各臂宏平均"),
            ("落盘与报告", "manifest + report.html"),
        ]
    if s in {"coding", "coding_infer"}:
        steps = [
            ("拉取 SWE-bench Lite", "题集与仓库镜像（可预热/缓存）"),
            (
                "产品 Turn 改码" if l1 else "组件直出补丁",
                "L1：edit_file 主路径" if l1 else "L0：bench 旁路生成 patch",
            ),
            ("收集补丁", "predictions / patch 落盘，统计产出率"),
        ]
        if coding_harness:
            steps.append(("Harness 评测", "官方 Docker resolve（耗时长）"))
        else:
            steps.append(("跳过 Harness", "默认不跑 Docker resolve；解决率可能为空"))
        steps.append(("生成报告", "manifest + report.html"))
        return steps
    return [
        ("准备", "读取配置与题集"),
        ("执行评测", f"套件 {suite_zh(s)}"),
        ("汇总指标", "写入 summary / metrics"),
        ("生成报告", "report.html"),
    ]


def flow_steps_for_ops_targets(
    targets: list[str],
    *,
    eval_path: str | None = None,
) -> list[tuple[str, str]]:
    labels = [suite_zh(t) for t in targets] or ["（未指定套件）"]
    return [
        ("选择评测目标", "、".join(labels)),
        (
            "按套件执行",
            f"路径：{_eval_path_label(eval_path)}；各套件 finish 后写出子报告",
        ),
        ("聚合报告", "Ops 汇总各子套件 HTML，供历史页打开"),
    ]


def render_flow_section(
    steps: list[tuple[str, str]],
    *,
    caption: str,
) -> str:
    if not steps:
        return ""
    items: list[str] = []
    for i, (title, detail) in enumerate(steps, start=1):
        if i > 1:
            items.append('<div class="flow-arrow" aria-hidden="true">→</div>')
        items.append(
            f"""
            <div class="flow-step" role="listitem">
              <span class="n">{i}</span>
              <div>
                <strong>{_esc(title)}</strong>
                <small>{_esc(detail)}</small>
              </div>
            </div>"""
        )
    return f"""
  <section class="card flow-card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">本次评测流程</h2>
    <p class="muted">{_esc(caption)}</p>
    <div class="flow" role="list">
      {"".join(items)}
    </div>
  </section>"""


def _shared_styles() -> str:
    return """
    :root {
      --bg: #f6f1e8; --ink: #1c1916; --muted: #6b635a; --line: #d9d0c3;
      --ok: #1f6b4a; --fail: #9b2c2c; --accent: #0f4c5c; --card: #fffdf8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; font-family: "Source Han Serif SC", "Noto Serif SC", "Songti SC",
        "Iowan Old Style", "Palatino Linotype", Palatino, serif;
      background:
        radial-gradient(1200px 600px at 10% -10%, #e7f0ef 0%, transparent 55%),
        linear-gradient(180deg, #f8f3eb, var(--bg));
      color: var(--ink); line-height: 1.45;
    }
    main { max-width: 960px; margin: 0 auto; padding: 2rem 1.25rem 4rem; }
    h1 { font-size: 1.75rem; margin: 0 0 .25rem; letter-spacing: -0.02em; }
    .sub { color: var(--muted); margin-bottom: 1.5rem; }
    .grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); }
    .card {
      background: var(--card); border: 1px solid var(--line); border-radius: 12px;
      padding: 1rem 1.1rem; box-shadow: 0 1px 0 rgba(28,25,22,.04);
    }
    .card strong { display: block; font-size: 1.4rem; }
    .card span { color: var(--muted); font-size: .85rem; }
    .metric { margin: .55rem 0; }
    .metric-label { display:flex; justify-content:space-between; font-size:.9rem; margin-bottom:.2rem; }
    .bar { height: 8px; background: #ece4d8; border-radius: 99px; overflow: hidden; }
    .bar i { display:block; height:100%; background: linear-gradient(90deg, var(--accent), #2a9d8f); }
    table { width:100%; border-collapse: collapse; font-size: .92rem; }
    th, td { border-bottom: 1px solid var(--line); padding: .55rem .35rem; vertical-align: top; text-align: left; }
    pre { margin: 0; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .78rem; }
    .st-pass, .st-completed, .st-ok { color: var(--ok); font-weight: 700; }
    .st-fail, .st-failed, .st-error { color: var(--fail); font-weight: 700; }
    .st-skipped, .st-pending, .st-cancelled, .st-canceled, .st-queued { color: var(--muted); }
    ol.process { padding-left: 1.1rem; }
    ol.process li { margin: .35rem 0; }
    ol.process time { color: var(--muted); font-size: .8rem; margin-right: .4rem; }
    .kind {
      display:inline-block; font-size:.7rem; letter-spacing:.04em;
      border:1px solid var(--line); border-radius: 999px; padding: .05rem .4rem; margin-right:.35rem;
      color: var(--accent);
    }
    .muted { color: var(--muted); }
    code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .85em; }
    .flow {
      display: flex; flex-wrap: wrap; align-items: stretch; gap: .55rem .35rem;
      margin-top: .75rem;
    }
    .flow-step {
      display: flex; gap: .55rem; align-items: flex-start;
      min-width: 9.5rem; max-width: 14rem; flex: 1 1 9.5rem;
      padding: .65rem .7rem; border: 1px solid var(--line); border-radius: 10px;
      background: #fbf7f0;
    }
    .flow-step .n {
      flex: 0 0 auto; width: 1.4rem; height: 1.4rem; border-radius: 999px;
      background: var(--accent); color: #fff; font-size: .75rem; font-weight: 700;
      display: inline-flex; align-items: center; justify-content: center;
      font-family: ui-sans-serif, system-ui, sans-serif;
    }
    .flow-step strong {
      display: block; font-size: .92rem; margin: 0 0 .15rem; font-weight: 700;
    }
    .flow-step small { display: block; color: var(--muted); font-size: .75rem; line-height: 1.35; }
    .flow-arrow {
      align-self: center; color: var(--accent); font-size: 1.1rem; padding: 0 .1rem;
      font-family: ui-sans-serif, system-ui, sans-serif;
    }
    @media (max-width: 640px) {
      .flow-arrow { display: none; }
      .flow-step { max-width: none; }
    }
    """


def _metric_bars(metrics: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, val in metrics.items():
        if not isinstance(val, (int, float)):
            continue
        width = float(val) if float(val) > 1.0 else float(val) * 100.0
        width = max(0.0, min(100.0, width))
        parts.append(
            f"""
            <div class="metric">
              <div class="metric-label"><span>{_esc(metric_label(str(key)))}</span>
                <strong>{_esc(f"{float(val):.4f}" if isinstance(val, float) else val)}</strong>
              </div>
              <div class="bar"><i style="width:{width:.1f}%"></i></div>
            </div>"""
        )
    return "\n".join(parts) or "<p class='muted'>无数值指标</p>"


def _flow_from_manifest(manifest: dict[str, Any]) -> str:
    suite = str(
        manifest.get("official_suite")
        or (manifest.get("model_meta") or {}).get("official_suite")
        or ""
    )
    meta = manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}
    eval_path = meta.get("eval_path") or manifest.get("eval_path")
    context_dry = meta.get("context_dry")
    if context_dry is None:
        context_dry = meta.get("dry")
    coding_harness = meta.get("harness")
    if isinstance(coding_harness, str):
        coding_harness = coding_harness.lower() in {"1", "true", "yes", "on"}
    steps = flow_steps_for_suite(
        suite,
        eval_path=str(eval_path) if eval_path is not None else None,
        context_dry=bool(context_dry) if context_dry is not None else None,
        coding_harness=bool(coding_harness) if coding_harness is not None else None,
    )
    caption = (
        f"套件：{suite_zh(suite)} · 路径：{_eval_path_label(eval_path)}"
    )
    return render_flow_section(steps, caption=caption)


def write_html_report(path: Path, manifest: dict[str, Any]) -> None:
    metrics = manifest.get("metrics") or (manifest.get("summary") or {}).get("metrics") or {}
    cases = manifest.get("cases") or []
    logs = manifest.get("logs") or []
    summary = manifest.get("summary") or {}
    result = manifest.get("result") if isinstance(manifest.get("result"), dict) else {}
    model_meta = (
        manifest.get("model_meta") if isinstance(manifest.get("model_meta"), dict) else {}
    )
    bucket_counts = (
        result.get("bucket_counts")
        or model_meta.get("bucket_counts")
        or {}
    )
    weak_hits = result.get("weak_hits_cases") or model_meta.get("weak_hits_cases") or []
    suite_median = result.get("suite_ndcg_median")
    if suite_median is None:
        suite_median = model_meta.get("suite_ndcg_median")

    case_rows = []
    for c in cases:
        m = c.get("metrics") or {}
        bucket = c.get("bucket") or ""
        st = str(c.get("status") or "")
        case_rows.append(
            f"<tr>"
            f"<td><code>{_esc(c.get('case_id'))}</code></td>"
            f"<td class='st-{_esc(st)}'>{_esc(status_zh(st))}</td>"
            f"<td>{_esc(bucket or '—')}</td>"
            f"<td><pre>{_esc(json.dumps(m, ensure_ascii=False, indent=2)[:800])}</pre></td>"
            f"<td>{_esc(c.get('error') or '—')}</td>"
            f"</tr>"
        )

    bucket_rows = []
    if isinstance(bucket_counts, dict) and bucket_counts:
        for name, n in sorted(bucket_counts.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
            bucket_rows.append(
                f"<tr><td><code>{_esc(name)}</code></td><td><strong>{_esc(n)}</strong></td></tr>"
            )

    weak_rows = []
    if isinstance(weak_hits, list):
        for item in weak_hits[:40]:
            if not isinstance(item, dict):
                continue
            hits = item.get("top_hits") or []
            hits_txt = json.dumps(hits[:5], ensure_ascii=False, indent=2)[:500]
            ndcg_v = item.get("ndcg_at_10")
            ndcg_txt = f"{float(ndcg_v):.4f}" if isinstance(ndcg_v, (int, float)) else "—"
            weak_rows.append(
                f"<tr>"
                f"<td><code>{_esc(item.get('case_id'))}</code></td>"
                f"<td>{_esc(item.get('bucket'))}</td>"
                f"<td>{_esc(ndcg_txt)}</td>"
                f"<td><pre>{_esc(item.get('query') or '—')}</pre></td>"
                f"<td><pre>{_esc(hits_txt)}</pre></td>"
                f"</tr>"
            )

    log_rows = []
    for item in logs:
        msg = item.get("message")
        if msg is None and item.get("kind") == "l2_probe":
            msg = json.dumps(
                {k: v for k, v in item.items() if k not in {"at", "kind", "level"}},
                ensure_ascii=False,
            )[:400]
        log_rows.append(
            f"<li><time>{_esc(item.get('at'))}</time> "
            f"<span class='kind'>{_esc(kind_zh(item.get('kind')))}</span> "
            f"{_esc(msg or '—')}</li>"
        )

    bucket_section = ""
    if bucket_rows:
        median_txt = (
            f"{float(suite_median):.4f}" if isinstance(suite_median, (int, float)) else "—"
        )
        bucket_section = f"""
  <section class="card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">分桶统计</h2>
    <p class="muted">本套件 nDCG 中位数 = {_esc(median_txt)}</p>
    <table>
      <thead><tr><th>分桶</th><th>数量</th></tr></thead>
      <tbody>{"".join(bucket_rows)}</tbody>
    </table>
  </section>"""

    weak_section = ""
    if weak_rows:
        weak_section = f"""
  <section class="card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">低分用例（nDCG@10 &lt; 中位数）</h2>
    <table>
      <thead><tr><th>用例</th><th>分桶</th><th>nDCG@10</th><th>查询</th><th>Top 命中</th></tr></thead>
      <tbody>{"".join(weak_rows)}</tbody>
    </table>
  </section>"""

    suite = manifest.get("official_suite") or ""
    run_status = manifest.get("status")
    title = manifest.get("title") or "官方评测报告"
    flow_section = _flow_from_manifest(manifest)

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>官方评测 · {_esc(title)}</title>
  <style>{_shared_styles()}</style>
</head>
<body>
<main>
  <h1>{_esc(title)}</h1>
  <p class="sub">
    套件=<code>{_esc(suite)}</code>（{_esc(suite_zh(suite))}） ·
    运行 ID=<code>{_esc(manifest.get("id"))}</code> ·
    状态=<strong class="st-{_esc(run_status)}">{_esc(status_zh(run_status))}</strong><br/>
    {_esc(manifest.get("created_at"))} → {_esc(manifest.get("finished_at"))}
  </p>

  <div class="grid">
    <div class="card"><span>用例总数</span><strong>{_esc(summary.get("total", 0))}</strong></div>
    <div class="card"><span>通过</span><strong>{_esc(summary.get("pass", 0))}</strong></div>
    <div class="card"><span>失败</span><strong>{_esc(summary.get("fail", 0))}</strong></div>
    <div class="card"><span>跳过</span><strong>{_esc(summary.get("skipped", 0))}</strong></div>
  </div>
{flow_section}
  <section class="card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">核心指标</h2>
    {_metric_bars(metrics if isinstance(metrics, dict) else {})}
  </section>
{bucket_section}
{weak_section}
  <section class="card" style="margin-top:1rem">
    <h2 style="margin-top:0;font-size:1.1rem">用例结果</h2>
    <table>
      <thead><tr><th>用例</th><th>状态</th><th>分桶</th><th>指标</th><th>错误</th></tr></thead>
      <tbody>{"".join(case_rows) or "<tr><td colspan=5 class='muted'>无用例</td></tr>"}</tbody>
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
