#!/usr/bin/env python3
"""阶段 0：用三组已观察卡片离线算正文相似度，建立阈值先验。

不进产品 Turn。HashEmbedder 只说明词法区分力；产品应用 ST 再看一遍。
期望（人眼）：夜行证 vs 执契、人间有灵 vs 灵籍 高；肉身 vs 家属 低。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_APP = ROOT / "services" / "runtime"
if str(RUNTIME_APP) not in sys.path:
    sys.path.insert(0, str(RUNTIME_APP))

from app.retrieval.embedder import cosine_similarity, embed_many, get_embedder  # noqa: E402
from app.writing.pond_similarity import (  # noqa: E402
    embedder_kind,
    embedder_is_lexical,
    pond_embed_text,
)

# 正文取自 docs/writing-module.md 三组卡片对照（书名遮去后的「这本书」+「开篇」）。
GROUPS: dict[str, list[dict[str, str]]] = {
    "night_papers": [
        {
            "title": "夜行证失效",
            "flavor": "跑腿、死人留下的证、三分钟确认，否则整车被带走。",
            "opening": "公共屏幕倒计时，地铁里三分钟确认，否则整车被带走。",
        },
        {
            "title": "人间有灵",
            "flavor": "异能已融入日常、直播事故、术法回声叫出母亲已注销的修士名号。",
            "opening": "直播事故里术法回声叫出母亲已注销的修士名号。",
        },
    ],
    "engines_apart": [
        {
            "title": "我的肉身不认天命",
            "flavor": "医院陪护，别人打进来的灵力练成自己的骨头；规则当场能用。",
            "opening": "攥住少爷手腕，先把踩氧气管的脚挪开。",
        },
        {
            "title": "仙人替我修炼",
            "flavor": "未来自己住进识海；金手指熟，但谁在用谁的身体能撑长篇。",
            "opening": "决斗台、妹妹断绝关系、当面回拨。",
        },
        {
            "title": "散修家属",
            "flavor": "停津贴、房租、后事、住院费；姐姐失去御火之后怎么过。",
            "opening": "津贴停了，房租和住院费还在，先把日子过下去。",
        },
    ],
    "axis_translated": [
        {
            "title": "执契",
            "flavor": "替人签字的跑腿；契把人写成第十八手；全城未结清的债往他身上认。",
            "opening": "笔离开受托人栏，楼上客户呼吸断了。",
        },
        {
            "title": "灵籍",
            "flavor": "考三次编制不过的片区巡查员；灵气按名分发；他是空的所以扛得住别人的灵力。",
            "opening": "早高峰翅膀拧铁门，编号是他上周登记的。",
        },
    ],
}

CROSS = [
    ("夜行证失效", "执契"),
    ("人间有灵", "灵籍"),
    ("我的肉身不认天命", "散修家属"),
]


def _index() -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for items in GROUPS.values():
        for it in items:
            out[it["title"]] = it
    return out


def main() -> int:
    embedder = get_embedder()
    kind = embedder_kind(embedder)
    lexical = embedder_is_lexical(embedder)
    catalog = _index()
    report: dict[str, object] = {
        "embedder": kind,
        "lexical": lexical,
        "note": (
            "HashEmbedder is lexical overlap only; ST is required to judge "
            "whether Turn-inner similarity can separate reskins from different books."
        ),
        "intra": {},
        "cross": {},
    }
    print(f"embedder={kind} lexical={lexical}")
    print(
        "prior expectation: 夜行证 vs 执契 and 人间有灵 vs 灵籍 high; "
        "肉身 vs 家属 low. If the three bands overlap, Turn-inner "
        "thresholds must stay very high (near-duplicate only)."
    )
    for name, items in GROUPS.items():
        vecs = embed_many(embedder, [pond_embed_text(it) for it in items])
        pairs = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                score = cosine_similarity(vecs[i], vecs[j])
                pairs.append(
                    {
                        "left": items[i]["title"],
                        "right": items[j]["title"],
                        "cos": round(float(score), 4),
                    }
                )
                print(f"  intra {name}: {items[i]['title']} vs {items[j]['title']} = {score:.4f}")
        report["intra"][name] = pairs  # type: ignore[index]
    for left, right in CROSS:
        a = catalog[left]
        b = catalog[right]
        vecs = embed_many(embedder, [pond_embed_text(a), pond_embed_text(b)])
        score = cosine_similarity(vecs[0], vecs[1])
        report["cross"][f"{left} vs {right}"] = round(float(score), 4)  # type: ignore[index]
        print(f"  cross {left} vs {right} = {score:.4f}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
