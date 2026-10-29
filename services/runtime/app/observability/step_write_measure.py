"""每步写入字节，以及抽样消息按规范化 JSON 再次出现的字节。

已见哈希只活在本进程里，不是内容寻址堆。集合满之后，新哈希不再加入，
也不算命中，避免测量本身变成只增不减的集合。插入失败时不提交哈希，
下一轮同一消息仍算未命中。
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from app.observability.metrics import metrics

_SEEN_CAP = 100_000
_seen: set[str] = set()
_lock = threading.Lock()


def canonical_json(value: Any) -> str:
    """规范化 JSON：键排序、保留非 ASCII、不可序列化的值用 str。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def clear_seen_hashes() -> None:
    with _lock:
        _seen.clear()


def classify_sample(messages: list[Any]) -> tuple[int, int, list[str]]:
    """统计本步抽样消息的规范字节和命中字节，不修改已见集合。

    返回:
        规范字节、命中字节、本步首次出现且集合仍有空位的哈希。
        同一条消息在本步出现两次时，第二次计入命中。
        集合已满时，新哈希的字节计入规范字节，不计入命中。
    """
    canonical = 0
    hit = 0
    pending: list[str] = []
    with _lock:
        room = _SEEN_CAP - len(_seen)
        local_new: set[str] = set()
        for message in messages:
            blob = canonical_json(message).encode("utf-8")
            digest = hashlib.sha256(blob).hexdigest()
            size = len(blob)
            canonical += size
            if digest in _seen or digest in local_new:
                hit += size
            elif len(pending) < room:
                pending.append(digest)
                local_new.add(digest)
    return canonical, hit, pending


def commit_seen(hashes: list[str]) -> None:
    """插入成功之后才把本步的新哈希记入已见集合。"""
    with _lock:
        for digest in hashes:
            if len(_seen) >= _SEEN_CAP:
                break
            _seen.add(digest)


def record_written_bytes(n: int) -> None:
    if n > 0:
        metrics.inc("storage_step_write_bytes", float(n))


def record_sample(canonical: int, hit: int) -> None:
    if canonical > 0:
        metrics.inc("storage_canonical_bytes", float(canonical))
    if hit > 0:
        metrics.inc("storage_canonical_hit_bytes", float(hit))
