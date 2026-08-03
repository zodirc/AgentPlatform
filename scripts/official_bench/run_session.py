from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .html_report import write_html_report
from .paths import ensure_dirs, reports_dir


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunSession:
    """Records process + results for one official-bench invocation."""

    def __init__(self, *, suite: str, title: str) -> None:
        ensure_dirs()
        self.run_id = str(uuid.uuid4())
        self.suite = suite
        self.title = title
        self.created_at = _utc_now()
        self.finished_at: str | None = None
        self.status = "running"
        self.error: str | None = None
        self.logs: list[dict[str, Any]] = []
        self.cases: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}
        self.extra: dict[str, Any] = {}
        self.dir = reports_dir() / "runs" / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._process = self.dir / "process.jsonl"
        self.log("run_started", f"{title} ({suite})", kind="run_started")

    def log(
        self,
        message: str,
        detail: str | None = None,
        *,
        kind: str = "log",
        level: str = "info",
    ) -> None:
        item = {
            "at": _utc_now(),
            "kind": kind,
            "level": level,
            "message": message if detail is None else f"{message}: {detail}",
            "detail": detail,
        }
        # Keep Ops-compatible shape
        item["message"] = message if detail is None else f"{message} — {detail}"
        self.logs.append(item)
        with self._process.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"[{self.suite}] {item['message']}", flush=True)

    def add_case(
        self,
        case_id: str,
        *,
        status: str,
        metrics: dict[str, Any] | None = None,
        error: str | None = None,
        steps: list[dict[str, Any]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "case_id": case_id,
            "status": status,
            "events": [],
            "steps": steps or [],
            "error": error,
            "metrics": metrics or {},
            "started_at": self.created_at,
            "finished_at": _utc_now(),
        }
        if extra:
            row.update(extra)
        self.cases.append(row)
        self.log(
            f"case {case_id} → {status}",
            json.dumps(metrics or {}, ensure_ascii=False)[:240],
            kind="case_finished",
        )
        # A-5: structured L2 probe line for offline bucket reports.
        l2 = row.get("l2") if isinstance(row.get("l2"), dict) else None
        if l2 is not None:
            probe = {
                "at": _utc_now(),
                "kind": "l2_probe",
                "case_id": case_id,
                "status": status,
                **l2,
            }
            if row.get("bucket") and "bucket" not in probe:
                probe["bucket"] = row["bucket"]
            self.logs.append(probe)
            with self._process.open("a", encoding="utf-8") as f:
                f.write(json.dumps(probe, ensure_ascii=False) + "\n")

    def finish(
        self,
        *,
        status: str = "completed",
        error: str | None = None,
        metrics: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.status = status
        self.error = error
        self.finished_at = _utc_now()
        if metrics:
            self.metrics = metrics
        summary = {
            "total": len(self.cases),
            "pass": sum(1 for c in self.cases if c.get("status") == "pass"),
            "fail": sum(1 for c in self.cases if c.get("status") == "fail"),
            "skipped": sum(1 for c in self.cases if c.get("status") == "skipped"),
            "pending": 0,
            "metrics": self.metrics,
        }
        manifest = {
            "id": self.run_id,
            "suite": "official",
            "official_suite": self.suite,
            "title": self.title,
            "status": self.status,
            "mode": "official",
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "summary": summary,
            "cases": self.cases,
            "logs": self.logs,
            "metrics": self.metrics,
            "result": result or {},
            "model_meta": {
                "suite": "official",
                "official_suite": self.suite,
                "title": self.title,
                **self.extra,
            },
            "report_html": str(self.dir / "report.html"),
            "process_log": str(self._process),
        }
        (self.dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (self.dir / "result.json").write_text(
            json.dumps(result or {"metrics": self.metrics}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        write_html_report(self.dir / "report.html", manifest)
        # latest pointers
        root = reports_dir()
        (root / f"latest_{self.suite}.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (root / "latest_run.json").write_text(
            json.dumps(
                {
                    "id": self.run_id,
                    "official_suite": self.suite,
                    "status": self.status,
                    "report_html": str(self.dir / "report.html"),
                    "dir": str(self.dir),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.log("run_finished", self.status, kind="run_finished")
        return manifest
