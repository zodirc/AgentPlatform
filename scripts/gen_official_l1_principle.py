#!/usr/bin/env python3
"""Principle diagram: official dataset → product path → score (Chinese PNG)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "ops"
FONT_PATH = ROOT / "docs" / "assets" / "fonts" / "wqy-microhei.ttc"

BG = (250, 250, 252)
INK = (22, 26, 34)
MUTED = (72, 80, 94)
LINE = (210, 214, 222)
BLUE = (36, 99, 168)
BLUE_BG = (232, 240, 250)
GREEN = (28, 118, 78)
GREEN_BG = (230, 245, 234)
ORANGE = (168, 96, 28)
ORANGE_BG = (255, 243, 224)
PURPLE = (92, 58, 148)
PURPLE_BG = (240, 234, 250)
CARD = (255, 255, 255)
BORDER = (210, 214, 220)


def F(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size)


def tw(d: ImageDraw.ImageDraw, t: str, f: ImageFont.ImageFont) -> int:
    b = d.textbbox((0, 0), t, font=f)
    return b[2] - b[0]


def wrap(d: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont, max_w: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        cur = ""
        for ch in para:
            if tw(d, cur + ch, f) <= max_w:
                cur += ch
            else:
                if cur:
                    out.append(cur)
                cur = ch
        if cur:
            out.append(cur)
    return out


def box(
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    title: str,
    body: str,
    *,
    fill=CARD,
    outline=BORDER,
    title_c=INK,
    ts: int = 14,
    bs: int = 12,
) -> int:
    ft, fb = F(ts), F(bs)
    tl = wrap(d, title, ft, w - 24)
    bl = wrap(d, body, fb, w - 24)
    h = 12 + len(tl) * 20 + 4 + len(bl) * 17 + 12
    d.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=fill, outline=outline, width=2)
    ty = y + 10
    for line in tl:
        d.text((x + 12, ty), line, fill=title_c, font=ft)
        ty += 20
    ty += 2
    for line in bl:
        d.text((x + 12, ty), line, fill=MUTED, font=fb)
        ty += 17
    return y + h


def arrow_down(d: ImageDraw.ImageDraw, x: int, y: int, gap: int = 20) -> int:
    y1 = y + gap
    d.line((x, y + 2, x, y1 - 7), fill=BLUE, width=3)
    d.polygon([(x - 5, y1 - 11), (x + 5, y1 - 11), (x, y1)], fill=BLUE)
    return y1 + 4


def arrow_right(d: ImageDraw.ImageDraw, x0: int, y: int, x1: int) -> None:
    d.line((x0, y, x1 - 7, y), fill=BLUE, width=3)
    d.polygon([(x1 - 10, y - 5), (x1 - 10, y + 5), (x1, y)], fill=BLUE)


def build() -> Path:
    W, H = 1680, 2100
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    OUT.mkdir(parents=True, exist_ok=True)

    d.text((40, 22), "原理图：官方评测集如何接入主 Agent 链路做真实模拟", fill=INK, font=F(24))
    d.text(
        (40, 56),
        "一句话：官方题 = 外部标准输入；我们只做「物化进 Work + 发一条真实 Turn」；裁判仍用官方指标。",
        fill=MUTED,
        font=F(13),
    )
    y = 88
    d.line((40, y, W - 40, y), fill=LINE, width=2)
    y += 14

    # Metaphor
    y = box(
        d,
        40,
        y,
        W - 80,
        "直观比喻",
        "把官方题集想成「标准考卷」。我们不另造考试机，而是把考卷复印件放进和用户一样的书桌（Work/sources），"
        "再请同一个考生（AgentEngine + 工具）当场作答，最后用官方答案卡打分。"
        "考的是书桌+考生能力，不是另开一间只有计算器的实验室。",
        fill=ORANGE_BG,
        outline=ORANGE,
        title_c=ORANGE,
        ts=15,
        bs=13,
    )
    y = arrow_down(d, W // 2, y, 18)

    # Three layers horizontal: 题集 | 接入 | 主链路 | 打分
    y_label = y
    d.rounded_rectangle((40, y_label, W - 40, y_label + 28), radius=6, fill=BLUE_BG, outline=BLUE_BG)
    d.text((52, y_label + 5), "横向四段：题是什么 → 怎么放进我们的世界 → 怎么像用户一样跑 → 怎么打官方分", fill=INK, font=F(13))
    y = y_label + 40

    col_w = (W - 100) // 4
    gap = 12
    xs = [40 + i * (col_w + gap) for i in range(4)]
    headers = [
        ("① 官方题集数据", ORANGE, ORANGE_BG),
        ("② 接入物化", PURPLE, PURPLE_BG),
        ("③ 真实主链路", GREEN, GREEN_BG),
        ("④ 官方指标", BLUE, BLUE_BG),
    ]
    for i, (title, c, bg) in enumerate(headers):
        d.rounded_rectangle((xs[i], y, xs[i] + col_w, y + 32), radius=8, fill=bg, outline=c, width=2)
        d.text((xs[i] + 10, y + 7), title, fill=c, font=F(14))
    y += 44

    # Row: common pipe arrows between columns (visual)
    row1_y = y
    # Column contents - shared height cards
    bodies = [
        (
            "三种标准考卷（小量）",
            "【检索 BEIR】\n"
            "· corpus：文档 id → 正文\n"
            "· queries：问题 id → 问句\n"
            "· qrels：问题→相关文档\n"
            "  （官方相关标注）\n\n"
            "【上下文 LongBench】\n"
            "· context：超长篇章\n"
            "· question / input：问题\n"
            "· answers：参考答案\n\n"
            "【编码 SWE-Lite】\n"
            "· instance_id / repo\n"
            "· problem_statement\n"
            "· （可选）官方 harness\n"
            "  判定是否 resolve",
        ),
        (
            "变成产品看得见的文件",
            "数据在 BENCH_DATA_DIR\n"
            "（缓存，不进 git）\n\n"
            "为每一题建隔离 Work：\n"
            "/data/ops-l1/<run>/…\n\n"
            "检索：\n"
            "sources/beir/<集>/<id>.txt\n"
            "→ Turn 外 sync 索引\n\n"
            "上下文：\n"
            "sources/passage.md\n"
            "= 整篇 context\n\n"
            "编码：\n"
            "problem.md = 题面\n"
            "（仓库挂载可加强）\n\n"
            "关键：只改「桌上有什么」，\n"
            "不改 AgentEngine 规则。",
        ),
        (
            "与用户同一条 Turn",
            "Session + StartTurn\n"
            "（ops_eval 可注入评测模型）\n\n"
            "Intake → AgentEngine：\n"
            "assemble → 模型 → 工具\n"
            "→ tool_result → 再循环\n\n"
            "检索题：调 search_sources\n"
            "上下文：read_file /\n"
            "  search_sources 读篇章\n"
            "编码：propose_patch 等\n\n"
            "全程写 turn_events\n"
            "（可归因：搜没搜、读没读）\n\n"
            "等到 turn.completed\n"
            "才算这题结束。",
        ),
        (
            "用官方尺子量结果",
            "检索：\n"
            "从 retrieval.completed\n"
            "的 ranked/hits 还原\n"
            "doc_id 排序列表\n"
            "→ nDCG@k / Recall@k\n"
            "（对照 qrels）\n\n"
            "上下文：\n"
            "终态答案文本\n"
            "→ 与 answers 算 F1/EM\n\n"
            "编码：\n"
            "抽出 unified diff\n"
            "→ patch_rate（辅）\n"
            "→ swebench harness\n"
            "  resolve（主，需 Docker）\n\n"
            "落盘 report + latest_*\n"
            "协议戳记 m2",
        ),
    ]
    bottoms = []
    for i, (title, body) in enumerate(bodies):
        colors = [ORANGE, PURPLE, GREEN, BLUE]
        bgs = [ORANGE_BG, PURPLE_BG, GREEN_BG, BLUE_BG]
        bottoms.append(
            box(
                d,
                xs[i],
                row1_y,
                col_w,
                title,
                body,
                fill=bgs[i],
                outline=colors[i],
                title_c=colors[i],
                ts=13,
                bs=11,
            )
        )
        if i < 3:
            mid_y = row1_y + 80
            arrow_right(d, xs[i] + col_w + 1, mid_y, xs[i + 1] - 1)
    y = max(bottoms) + 8
    y = arrow_down(d, W // 2, y, 18)

    # Concrete example strip
    d.rounded_rectangle((40, y, W - 40, y + 28), radius=6, fill=GREEN_BG, outline=GREEN_BG)
    d.text((52, y + 5), "举例：一道 BEIR 检索题如何「真模拟」", fill=GREEN, font=F(13))
    y += 36

    steps = [
        ("题集里", "query: “Does caffeine…?”\nqrels: doc#42 相关"),
        ("物化后", "sources/…/42.txt\n= 该篇论文摘要\n+ 索引已 sync"),
        ("Turn 里", "用户消息带该问句\n模型调用\nsearch_sources"),
        ("事件里", "ranked: [42, 7, …]\n= 工具真实召回序"),
        ("打分", "用 qrels 算\nnDCG@10\n= 官方同款指标"),
    ]
    sw = (W - 40 - 6 * 10) // 5
    for i, (t, b) in enumerate(steps):
        x = 40 + i * (sw + 10)
        box(d, x, y, sw, t, b, fill=CARD, outline=GREEN, title_c=GREEN, ts=12, bs=11)
        if i < 4:
            arrow_right(d, x + sw + 1, y + 40, x + sw + 9)
    y += 110
    y = arrow_down(d, W // 2, y, 16)

    # What is NOT
    y = box(
        d,
        40,
        y,
        W - 80,
        "刻意不做的「假模拟」（L0 对照才这样）",
        "× 检索：跳过 Turn，直接 store.search(hybrid) 对着 corpus 算 nDCG\n"
        "× 上下文：把整篇塞进单条 user，只跑 ContextEngine.assemble，不经 read_file\n"
        "× 编码：bench 直连 chat 要一段 diff，不经 propose_patch / 工具链\n"
        "这些能测组件，但不能代表用户真实交互。主指数只用 L1。",
        fill=(255, 236, 236),
        outline=(160, 50, 50),
        title_c=(160, 50, 50),
        ts=14,
        bs=12,
    )
    y += 14

    # Formula
    y = box(
        d,
        40,
        y,
        W - 80,
        "原理公式",
        "真实模拟分  =  f( 官方题面物化进 Work ,  主 Agent Turn/工具/上下文治理 ,  官方裁判 )\n"
        "其中 f 不改变 loop；只改变「桌上材料」和「读事件的方式」。\n"
        "因此：涨分 ⇒ 应来自 RAG/Harness/预算等工程变好；而不是换一把更松的尺子。",
        fill=BLUE_BG,
        outline=BLUE,
        title_c=BLUE,
        ts=14,
        bs=12,
    )
    y += 16
    d.line((40, y, W - 40, y), fill=LINE, width=1)
    y += 10
    d.text(
        (40, y),
        "输出：docs/assets/ops/official-l1-principle-zh.png · 脚本：scripts/gen_official_l1_principle.py · 详流程见 official-l1-agent-path-flow-zh.png",
        fill=MUTED,
        font=F(11),
    )
    y += 28

    path = OUT / "official-l1-principle-zh.png"
    img.crop((0, 0, W, y + 16)).save(path, "PNG", optimize=True)
    print(f"wrote {path}")
    return path


if __name__ == "__main__":
    build()
