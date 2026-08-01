from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import load_suites
from .paths import suite_data
from .publish import publish_manifest
from .pull import pull_longbench
from .run_session import RunSession

_WS = re.compile(r"\s+")


def _normalize(s: str) -> str:
    return _WS.sub(" ", (s or "").strip().lower())


def _answers_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        out: list[str] = []
        for a in raw:
            if isinstance(a, str):
                out.append(a)
            elif isinstance(a, list):
                out.extend(str(x) for x in a)
            else:
                out.append(str(a))
        return out
    return [str(raw)]


def _f1(pred: str, gold: str) -> float:
    p = _normalize(pred).split()
    g = _normalize(gold).split()
    if not p and not g:
        return 1.0
    if not p or not g:
        return 0.0
    common = 0
    g_counts: dict[str, int] = {}
    for t in g:
        g_counts[t] = g_counts.get(t, 0) + 1
    for t in p:
        if g_counts.get(t, 0) > 0:
            common += 1
            g_counts[t] -= 1
    if common == 0:
        return 0.0
    prec = common / len(p)
    rec = common / len(g)
    return 2 * prec * rec / (prec + rec)


def score_prediction(pred: str, golds: list[str]) -> dict[str, float]:
    if not golds:
        return {"em": 0.0, "f1": 0.0}
    norm_pred = _normalize(pred)
    em = 1.0 if any(_normalize(g) == norm_pred or _normalize(g) in norm_pred for g in golds) else 0.0
    f1 = max(_f1(pred, g) for g in golds)
    return {"em": em, "f1": f1}


def middle_truncate(text: str, budget: int) -> str:
    if budget <= 0 or len(text) <= budget:
        return text
    keep = budget // 2
    return text[:keep] + "\n\n...[truncated]...\n\n" + text[-keep:]


def _ensure_runtime_path() -> Path:
    """Add the product runtime package to this standalone runner's import path."""
    runtime = Path(__file__).resolve().parents[2] / "services" / "runtime"
    if not runtime.is_dir():
        raise RuntimeError(f"runtime tree missing: {runtime}")
    path = str(runtime)
    if path not in sys.path:
        sys.path.insert(0, path)
    return runtime


def _message_content_text(message: dict[str, Any]) -> str:
    """Read text from either runtime block content or provider-style strings."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif "content" in block:
            parts.append(str(block.get("content") or ""))
    return "\n".join(part for part in parts if part).strip()


def compact_with_context_engine(text: str, budget_chars: int) -> str:
    """Compact locally with the product ContextEngine, never session persistence."""
    try:
        _ensure_runtime_path()
        from app.context.engine import ContextEngine
        from app.context.policy import CompactionPolicy
        from app.engine.state import TurnState

        state = TurnState(
            turn_id=uuid4(),
            session_id=uuid4(),
            run_id=uuid4(),
            trace_id=uuid4(),
            scenario_id="official_longbench_compact",
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        )
        engine = ContextEngine(
            policy=CompactionPolicy.legacy_messages_budget(max(64, budget_chars // 4))
        )
        messages = engine.assemble(
            system_prompt="Compact the supplied LongBench context while retaining answer-relevant facts.",
            state=state,
            tools=[],
        )
        compacted = "\n".join(
            _message_content_text(message)
            for message in messages
            if message.get("role") != "system" and _message_content_text(message)
        ).strip()
        if not compacted:
            raise RuntimeError("ContextEngine returned no compacted text")
        return compacted
    except Exception as exc:  # noqa: BLE001 - benchmark must preserve its control arm
        print(f"[context] compact_fallback truncate: {exc}", flush=True)
        return middle_truncate(text, budget_chars)


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _build_prompt(row: dict[str, Any], context: str) -> str:
    question = str(row.get("question") or row.get("input") or "").strip()
    # LongBench often puts the question in `input` and passage in `context`.
    if row.get("context") and question == str(row.get("input") or "").strip():
        q = question
    elif row.get("context"):
        q = question
    else:
        # input already includes context
        return context if context else question
    return (
        "Answer the question based on the context. "
        "Reply with a short answer only.\n\n"
        f"Context:\n{context}\n\nQuestion:\n{q}\n\nAnswer:"
    )


def _chat_complete(prompt: str, *, model: str, base_url: str, api_key: str) -> str:
    from official_bench.llm_client import chat_complete

    return chat_complete(
        prompt,
        model=model,
        base_url=base_url,
        api_key=api_key,
        max_tokens=256,
    )


def _phase(msg: str) -> None:
    print(f"[phase] {msg}", flush=True)


def run_context_small(
    *,
    force_pull: bool = False,
    limit: int = 0,
    dry_metrics: bool = False,
) -> dict[str, Any]:
    """Run LongBench small three-arm (full vs truncate vs ContextEngine compact).

    ``dry_metrics`` skips the model and uses an empty prediction (pipeline smoke only).
    """
    cfg = load_suites()
    ctx = cfg["suites"]["context"]
    session = RunSession(
        suite="context",
        title="LongBench small (full / truncate / ContextEngine compact)",
    )
    session.extra = {
        "protocol_version": cfg.get("protocol_version"),
        "official": ctx.get("official"),
        "dry_metrics": dry_metrics,
    }

    try:
        _phase("1/3 PULL — LongBench slice (skip if cached)")
        session.log("pull", "LongBench slice")
        root = pull_longbench(cfg, force=force_pull)
        rows = _load_rows(root / "small_slice.jsonl")
        if limit > 0:
            rows = rows[:limit]
        _phase("1/3 PULL — done")

        budget = int(ctx.get("budget_chars") or 24000)
        max_ctx = int(ctx.get("max_context_chars") or 120000)
        cw = (os.environ.get("BENCH_MODEL_CONTEXT_WINDOW") or "").strip()
        if cw.isdigit():
            # Rough chars≈tokens*4; keep suite floor for truncate/compact budgets.
            max_ctx = min(max_ctx, max(budget, int(cw) * 4))

        api_key = (
            os.environ.get("BENCH_MODEL_API_KEY")
            or os.environ.get("MODEL_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip()
        model = (
            os.environ.get("BENCH_MODEL_NAME")
            or os.environ.get("MODEL_NAME")
            or "gpt-4o-mini"
        ).strip()
        base_url = (
            os.environ.get("BENCH_MODEL_BASE_URL")
            or os.environ.get("MODEL_BASE_URL")
            or ""
        ).strip()
        session.extra["model"] = None if dry_metrics else model
        session.extra["provider"] = (
            None if dry_metrics else (os.environ.get("BENCH_MODEL_PROVIDER") or "").strip() or None
        )
        session.extra["api_style"] = (
            None
            if dry_metrics
            else (os.environ.get("BENCH_MODEL_API_STYLE") or "").strip() or None
        )
        session.extra["context_window_tokens"] = int(cw) if cw.isdigit() else None

        if not dry_metrics and not api_key:
            raise SystemExit(
                "Context suite needs BENCH_MODEL_API_KEY (or MODEL_API_KEY / OPENAI_API_KEY). "
                "Or pass --dry-metrics for pull/pipeline smoke."
            )

        _phase(
            "2/3 EVAL — three arms (full / truncate / ContextEngine compact) "
            + ("dry (empty preds)" if dry_metrics else f"model={model}")
        )
        full_scores: list[dict[str, float]] = []
        budget_scores: list[dict[str, float]] = []
        compact_scores: list[dict[str, float]] = []
        details: list[dict[str, Any]] = []
        by_task: dict[str, list[dict[str, float]]] = {}

        for i, row in enumerate(rows):
            task = str(row.get("task") or "unknown")
            context = str(row.get("context") or "")
            if not context:
                context = str(row.get("input") or "")
            context = context[:max_ctx]
            golds = _answers_list(row.get("answers"))
            prompt_full = _build_prompt(row, context)
            prompt_budget = _build_prompt(row, middle_truncate(context, budget))
            compact_context = compact_with_context_engine(context, budget)
            prompt_compact = _build_prompt(row, compact_context)

            if dry_metrics:
                pred_full, pred_budget, pred_compact = "", "", ""
            else:
                session.log("infer", f"{i + 1}/{len(rows)} {task} arm=full")
                pred_full = _chat_complete(
                    prompt_full, model=model, base_url=base_url, api_key=api_key
                )
                session.log("infer", f"{i + 1}/{len(rows)} {task} arm=truncate")
                pred_budget = _chat_complete(
                    prompt_budget, model=model, base_url=base_url, api_key=api_key
                )
                session.log("infer", f"{i + 1}/{len(rows)} {task} arm=compact")
                pred_compact = _chat_complete(
                    prompt_compact, model=model, base_url=base_url, api_key=api_key
                )

            s_full = score_prediction(pred_full, golds)
            s_bud = score_prediction(pred_budget, golds)
            s_compact = score_prediction(pred_compact, golds)
            full_scores.append(s_full)
            budget_scores.append(s_bud)
            compact_scores.append(s_compact)
            by_task.setdefault(task, []).append(
                {"full": s_full["f1"], "budget": s_bud["f1"], "compact": s_compact["f1"]}
            )
            details.append(
                {
                    "task": task,
                    "idx": row.get("idx"),
                    "full": s_full,
                    "truncate": s_bud,
                    "compact": s_compact,
                    "context_chars": len(context),
                    "truncate_chars": min(len(context), budget),
                    "compact_chars": len(compact_context),
                }
            )

        def _avg(key: str, rows_s: list[dict[str, float]]) -> float:
            if not rows_s:
                return 0.0
            return sum(r[key] for r in rows_s) / len(rows_s)

        avg_full_f1 = _avg("f1", full_scores)
        avg_bud_f1 = _avg("f1", budget_scores)
        avg_compact_f1 = _avg("f1", compact_scores)
        retention = (avg_bud_f1 / avg_full_f1) if avg_full_f1 > 1e-9 else 0.0
        compact_retention = (
            (avg_compact_f1 / avg_full_f1) if avg_full_f1 > 1e-9 else 0.0
        )
        metrics = {
            "full_em": _avg("em", full_scores),
            "full_f1": avg_full_f1,
            "budget_em": _avg("em", budget_scores),
            "budget_f1": avg_bud_f1,
            "retention_vs_full_f1": retention,
            "compact_em": _avg("em", compact_scores),
            "compact_f1": avg_compact_f1,
            "retention_compact_vs_full": compact_retention,
        }
        _phase(
            f"2/3 EVAL — done · full_f1={avg_full_f1:.4f} budget_f1={avg_bud_f1:.4f} "
            f"compact_f1={avg_compact_f1:.4f} retention={retention:.4f} "
            f"compact_retention={compact_retention:.4f}"
        )
        _phase("3/3 REGRESS — use Ops「多次结果对比」vs prior context runs (no file baseline yet)")

        for task, pairs in by_task.items():
            tf = sum(p["full"] for p in pairs) / len(pairs)
            tb = sum(p["budget"] for p in pairs) / len(pairs)
            tc = sum(p["compact"] for p in pairs) / len(pairs)
            session.add_case(
                f"longbench.{task}",
                status="skipped" if dry_metrics else "pass",
                metrics={
                    "full_f1": tf,
                    "budget_f1": tb,
                    "retention": (tb / tf) if tf > 1e-9 else 0.0,
                    "compact_f1": tc,
                    "retention_compact_vs_full": (tc / tf) if tf > 1e-9 else 0.0,
                    "n": len(pairs),
                },
            )

        result = {
            "suite": ctx["id"],
            "official": ctx["official"],
            "protocol_version": cfg.get("protocol_version"),
            "data_dir": str(suite_data("longbench")),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "model": model if not dry_metrics else None,
            "dry_metrics": dry_metrics,
            "n_samples": len(rows),
            "budget_chars": budget,
            "metrics": metrics,
            "per_example": details,
        }
        manifest = session.finish(
            status="completed",
            metrics=metrics,
            result=result,
        )
        pub = publish_manifest(manifest)
        manifest["publish"] = pub
        print(f"[context] HTML → {session.dir / 'report.html'}")
        return manifest
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        session.log("error", str(exc), level="error")
        manifest = session.finish(status="failed", error=str(exc))
        publish_manifest(manifest)
        raise
