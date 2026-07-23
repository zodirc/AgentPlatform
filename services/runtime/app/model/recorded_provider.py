from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

import asyncio

from app.model.gateway import ModelGateway, ModelResponse, StubModelProvider
from app.settings import settings


_RECORDING_RE = re.compile(r"\[recording:([^\]]+)\]")


class RecordedModelProvider:
    """Replay model responses from eval/recordings/{case_id}.json."""

    def __init__(self, case_id: str) -> None:
        self._case_id = case_id
        self._steps = self._load_steps(case_id)
        self._index = 0
        self._stub = StubModelProvider()

    def _load_steps(self, case_id: str) -> list[dict[str, Any]]:
        root = Path(settings.recordings_dir)
        if not root.is_dir():
            root = Path(__file__).resolve().parents[5] / "eval" / "recordings"
        path = root / f"{case_id.replace('.', '_')}.json"
        if not path.is_file():
            path = root / f"{case_id}.json"
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("steps", []))

    async def stream(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        abort: asyncio.Event | None = None,
    ) -> AsyncIterator[str | ModelResponse]:
        if self._index < len(self._steps):
            step = self._steps[self._index]
            self._index += 1
            text = step.get("text")
            if text:
                for chunk in _chunk(str(text)):
                    yield chunk
            for call in step.get("tool_calls", []):
                yield ModelResponse(
                    tool_calls=[
                        {
                            "id": call.get("id", f"call_{uuid4().hex[:8]}"),
                            "name": call["name"],
                            "input": call.get("input", {}),
                        }
                    ],
                    output_tokens=8,
                )
            if not step.get("tool_calls") and text:
                yield ModelResponse(text=str(text), output_tokens=len(str(text)) // 4)
            return
        async for chunk in self._stub.stream(messages=messages, tools=tools, abort=abort):
            yield chunk


def recording_case_id(messages: list[dict[str, Any]]) -> str | None:
    for msg in messages:
        for block in msg.get("content", []):
            if block.get("type") != "text":
                continue
            text = str(block.get("text", ""))
            match = _RECORDING_RE.search(text)
            if match:
                return match.group(1)
    return None


def _chunk(text: str, size: int = 12) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


def create_recorded_gateway(messages: list[dict[str, Any]]) -> ModelGateway | None:
    from app.model.turn_override import current_turn_model_mode

    effective_mode = current_turn_model_mode() or settings.model_mode
    if effective_mode != "recorded":
        return None
    case_id = recording_case_id(messages)
    if not case_id:
        return None
    return ModelGateway(RecordedModelProvider(case_id))
