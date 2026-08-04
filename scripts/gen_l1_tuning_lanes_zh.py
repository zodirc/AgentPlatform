#!/usr/bin/env python3
"""Current product flowcharts; annotate which steps we introduced.

Layout: vertical spine + right callouts; auto-sized boxes; no overlap/clipping.

Outputs:
  docs/topics/retrieval-tuning-flowchart.png
  docs/topics/context-tuning-flowchart.png

Run: python3 scripts/gen_l1_tuning_lanes_zh.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "topics"

def _pick_cjk_font() -> str:
    candidates = [
        ROOT / ".cache" / "fonts" / "wqy-zenhei.ttc",
        ROOT / ".cache" / "fonts" / "NotoSansCJK-Regular.ttc",
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


FONT_REG = _pick_cjk_font()
FONT_MED = FONT_REG
FONT_BOLD = FONT_REG

BG = (253, 253, 253)
INK = (20, 24, 32)
MUTED = (80, 88, 100)

STEP = (46, 125, 70)
STEP_FILL = (242, 249, 242)
MODEL = (40, 100, 170)
MODEL_FILL = (235, 243, 252)
DECIDE = (190, 150, 40)
DECIDE_FILL = (255, 250, 230)
OURS = (200, 90, 40)
NOTE = (170, 55, 55)
NOTE_FILL = (252, 240, 240)
BORDER = (190, 196, 204)
WHITE = (255, 255, 255)
GRAY_FILL = (245, 245, 248)


def F(size: int, *, bold: bool = False, medium: bool = False):
    path = FONT_BOLD if bold else (FONT_MED if medium else FONT_REG)
    try:
        return ImageFont.truetype(path, size=size, index=0)
    except OSError:
        return ImageFont.load_default()


def tw(draw, text, f) -> int:
    b = draw.textbbox((0, 0), text, font=f)
    return b[2] - b[0]


def th(draw, text, f) -> int:
    b = draw.textbbox((0, 0), text, font=f)
    return b[3] - b[1]


def wrap(draw, text: str, f, max_w: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        if para == "":
            out.append("")
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if tw(draw, trial, f) <= max_w:
                cur = trial
            else:
                if cur:
                    out.append(cur)
                cur = ch
        if cur:
            out.append(cur)
    return out


def rr(draw, xy, r=10, fill=None, outline=None, width=2):
    draw.rounded_rectangle(xy, radius=r, fill=fill, outline=outline, width=width)


def v_arrow(draw, x, y0, y1):
    if y1 - y0 < 12:
        return
    draw.line((x, y0, x, y1 - 8), fill=INK, width=2)
    draw.polygon([(x - 6, y1 - 10), (x + 6, y1 - 10), (x, y1)], fill=INK)


def diamond(draw, cx, cy, w, h, text):
    pts = [(cx, cy - h // 2), (cx + w // 2, cy), (cx, cy + h // 2), (cx - w // 2, cy)]
    draw.polygon(pts, fill=DECIDE_FILL, outline=DECIDE)
    draw.line(pts + [pts[0]], fill=DECIDE, width=2)
    f = F(12, medium=True)
    lines = wrap(draw, text, f, max(60, w // 2))
    line_h = max(th(draw, "国", f) + 4, 18)
    ty = cy - (len(lines) * line_h) // 2 + 1
    for line in lines:
        draw.text((cx - tw(draw, line, f) // 2, ty), line, fill=INK, font=f)
        ty += line_h


def step_metrics(draw, w: int, title: str, body: str, *, ours: bool):
    badge_w = tw(draw, "我们加的", F(11, bold=True)) + 22 if ours else 0
    title_f, body_f = F(14, medium=True), F(12)
    # keep title clear of the orange badge
    title_max = w - 40 - (badge_w + 16 if ours else 0)
    tlines = wrap(draw, title, title_f, title_max)
    blines = wrap(draw, body, body_f, w - 40)
    title_lh = max(th(draw, "国Ag", title_f) + 8, 24)
    body_lh = max(th(draw, "国Ag", body_f) + 7, 20)
    top, mid, bot = 16, 10, 24
    h = top + len(tlines) * title_lh + mid + len(blines) * body_lh + bot
    return h, title_f, body_f, title_max, tlines, blines, title_lh, body_lh, badge_w, top, mid


def step_h(draw, w: int, title: str, body: str, *, ours: bool) -> int:
    return step_metrics(draw, w, title, body, ours=ours)[0]


def draw_step(draw, x, y, w, title, body, *, kind="step", ours: bool = False) -> int:
    h, title_f, body_f, title_max, tlines, blines, title_lh, body_lh, badge_w, top, mid = step_metrics(
        draw, w, title, body, ours=ours
    )
    fill, outline = (MODEL_FILL, MODEL) if kind == "model" else (STEP_FILL, STEP)
    rr(draw, (x, y, x + w, y + h), 10, fill=fill, outline=outline, width=2)

    if ours:
        tag = "我们加的"
        tw_ = tw(draw, tag, F(11, bold=True))
        bw = tw_ + 22
        rr(draw, (x + w - bw - 12, y + 12, x + w - 12, y + 32), 6, fill=OURS)
        draw.text((x + w - bw - 5, y + 14), tag, fill=WHITE, font=F(11, bold=True))

    ty = y + top
    for line in tlines:
        draw.text((x + 18, ty), line, fill=INK, font=title_f)
        ty += title_lh
    ty += mid
    for line in blines:
        draw.text((x + 18, ty), line, fill=MUTED, font=body_f)
        ty += body_lh
    return y + h


def note_metrics(draw, w: int, body: str):
    body_f = F(11)
    lines = wrap(draw, body, body_f, w - 40)
    body_lh = max(th(draw, "国Ag", body_f) + 7, 18)
    top, head, mid, bot = 14, 24, 10, 20
    h = top + head + mid + len(lines) * body_lh + bot
    return h, body_f, lines, body_lh, top, head, mid


def note_h(draw, w: int, body: str) -> int:
    return note_metrics(draw, w, body)[0]


def draw_note(draw, x, y, w, body) -> int:
    h, body_f, lines, body_lh, top, head, mid = note_metrics(draw, w, body)
    rr(draw, (x, y, x + w, y + h), 10, fill=NOTE_FILL, outline=NOTE, width=2)
    draw.text((x + 18, y + top), "为何加 · 是否有效", fill=NOTE, font=F(12, bold=True))
    ty = y + top + head + mid
    for line in lines:
        draw.text((x + 18, ty), line, fill=MUTED, font=body_f)
        ty += body_lh
    return y + h


def draw_info(draw, x, y, w, title: str, body: str) -> int:
    body_f = F(12)
    lines = wrap(draw, body, body_f, w - 40)
    body_lh = max(th(draw, "国Ag", body_f) + 7, 20)
    top, head, mid, bot = 14, 24, 10, 20
    h = top + head + mid + len(lines) * body_lh + bot
    rr(draw, (x, y, x + w, y + h), 10, fill=GRAY_FILL, outline=BORDER, width=2)
    draw.text((x + 18, y + top), title, fill=INK, font=F(13, bold=True))
    ty = y + top + head + mid
    for line in lines:
        draw.text((x + 18, ty), line, fill=MUTED, font=body_f)
        ty += body_lh
    return y + h


def header(draw, w, title, subtitle) -> int:
    draw.text((36, 20), title, fill=INK, font=F(24, bold=True))
    y = 56
    for line in wrap(draw, subtitle, F(13), w - 72):
        draw.text((36, y), line, fill=MUTED, font=F(13))
        y += 20
    y += 10
    rr(draw, (36, y, 58, y + 16), 4, fill=STEP_FILL, outline=STEP, width=2)
    draw.text((66, y - 1), "当前流程步骤", fill=MUTED, font=F(12))
    rr(draw, (190, y, 212, y + 16), 4, fill=MODEL_FILL, outline=MODEL, width=2)
    draw.text((220, y - 1), "模型相关", fill=MUTED, font=F(12))
    rr(draw, (310, y, 390, y + 16), 4, fill=OURS, outline=OURS, width=1)
    draw.text((318, y), "我们加的", fill=WHITE, font=F(11, bold=True))
    draw.text((400, y - 1), "= 已进入现行流程的优化点（右侧说明）", fill=MUTED, font=F(12))
    return y + 36


def footer(draw, y, w, text: str) -> int:
    body_f = F(12)
    lines = wrap(draw, text, body_f, w - 100)
    body_lh = max(th(draw, "国Ag", body_f) + 7, 20)
    top, head, mid, bot = 14, 24, 10, 18
    h = top + head + mid + len(lines) * body_lh + bot
    rr(draw, (36, y, w - 36, y + h), 10, fill=NOTE_FILL, outline=NOTE, width=2)
    draw.text((50, y + top), "怎么读这张图", fill=NOTE, font=F(13, bold=True))
    ty = y + top + head + mid
    for line in lines:
        draw.text((50, ty), line, fill=MUTED, font=body_f)
        ty += body_lh
    return y + h


def save(img: Image.Image, name: str, bottom: int) -> Path:
    path = OUT / name
    cropped = img.crop((0, 0, img.width, min(img.height, bottom + 32)))
    cropped.save(path, "PNG", optimize=True)
    print(f"wrote {path} ({path.stat().st_size // 1024} KiB, {cropped.size[0]}x{cropped.size[1]})")
    return path


GAP = 36
NOTE_GAP = 22


def fig_retrieval() -> Path:
    W, H = 1560, 2400
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    y0 = header(
        draw,
        W,
        "当前检索流程（writing / intel · search_sources）",
        "整图是系统现在实际怎么跑。带橙角标的步骤 = 我们优化后进入现行链路的位置；右侧写清为何加入、是否有效。",
    )

    bx, bw = 64, 520
    nx, nw = 860, 650
    cx = bx + bw // 2
    cy = y0
    right_y = y0

    right_y = draw_info(
        draw,
        nx,
        right_y,
        nw,
        "并行 · Index 面（Turn 外）",
        "切块、嵌入、目录监视与同步在交互外完成。用户提问热路径只读已有投影，不同步建库。",
    )
    right_y += 10
    right_y = draw_note(
        draw,
        nx,
        right_y,
        nw,
        "§14 / RET-4（2026-08-05）：向量默认已退役 MiniLM。"
        "make up 检测：合适 GPU（VRAM≥8GiB）→ thenlper/gte-large@1024（INDEX≈10）；"
        "否则 → thenlper/gte-small@384（INDEX≈9）。L0 冒烟 gte-small vs MiniLM macro +9.05pp。"
        "换模后须全库重嵌；未重嵌禁止只改查询模型。无 GPU 机用 small 即可测。",
    )
    right_y += 18

    def place_step(title, body, *, kind="step", ours=False, note_body: str | None = None):
        nonlocal cy, right_y
        h = step_h(draw, bw, title, body, ours=ours)
        if note_body:
            nh = note_h(draw, nw, note_body)
            draw_step(draw, bx, cy, bw, title, body, kind=kind, ours=ours)
            ny = max(cy, right_y)
            draw_note(draw, nx, ny, nw, note_body)
            row = max(h, (ny + nh) - cy)
            right_y = ny + nh + NOTE_GAP
        else:
            draw_step(draw, bx, cy, bw, title, body, kind=kind, ours=ours)
            row = h
        bottom = cy + row
        v_arrow(draw, cx, bottom, bottom + GAP)
        cy = bottom + GAP

    place_step(
        "1. 用户 Turn",
        "writing / intel 场景下 AgentEngine：assemble → model → tools。模型自行决定是否检索（软预算≤2，硬闸≤3）。",
    )
    place_step(
        "2. 调用 search_sources",
        "入参：query、limit（现行默认 30）、可选 path_prefix。解析库范围后走 hybrid；查询路径不同步重建索引。",
    )
    place_step(
        "3. 召回与融合排序",
        "向量 ANN 与 BM25 并行 → RRF 融合 → 文档到 chunk 两级整理 → 轻量词面加分。重型 cross-encoder 默认不开。",
    )
    place_step(
        "4. 生成命中列表（不做静默改序）",
        "按融合序输出命中。不再用「摘录是否盖住关键词」偷偷重排（该层默认关闭）。",
        ours=True,
        note_body=(
            "流程里曾插入静默重排；对照后开关与否宏效果无稳定差别 → 从现行默认路径拿掉，"
            "避免不可解释的二次排序。可行且更干净。"
        ),
    )
    place_step(
        "5. 整理给模型看的结果",
        "更深召回与约 400 字摘录；前几条详摘，其余 path/title/分数一行摘要。"
        "相对第一名的 0–100 分（保留原分）；过弱提示 low_score。有命中则读文件，勿 list_dir「确认」。",
        ours=True,
        note_body=(
            "抬深度 + 分层呈现：避免上下文预算把长摘录截光；相对分让弱分提示能触发；契约减少逛库。"
            "可行；宏检索分持平符合「呈现/契约不改公式」预期。保留在现行流程。"
        ),
    )
    place_step(
        "6. 落事件 retrieval.completed",
        "审计 / 后续逻辑使用带融合原分的 ranked 列表；与模型所见的相对分分开。",
    )

    dh = 78
    diamond(draw, cx, cy + dh // 2, 220, dh, "还要再搜一次？")
    # chip stays in the gutter, fully between spine and notes
    mid_l, mid_r = bx + bw + 20, nx - 20
    chip_y = cy + 18
    rr(draw, (mid_l, chip_y, mid_r, chip_y + 44), 8, fill=GRAY_FILL, outline=BORDER, width=1)
    draw.line((cx + 110, cy + dh // 2, mid_l, cy + dh // 2), fill=INK, width=2)
    chip = "否 → 读命中 / 直接作答"
    draw.text((mid_l + (mid_r - mid_l - tw(draw, chip, F(12))) // 2, chip_y + 14), chip, fill=MUTED, font=F(12))
    v_arrow(draw, cx, cy + dh, cy + dh + GAP)
    yes = "是 · 弱命中"
    yx = cx + 16
    yy = cy + dh + 4
    draw.rectangle((yx - 4, yy - 2, yx + tw(draw, yes, F(12)) + 8, yy + 18), fill=BG)
    draw.text((yx, yy), yes, fill=MUTED, font=F(12))
    cy = cy + dh + GAP

    place_step(
        "7. 第二次检索",
        "仍受每轮次数上限约束。保持同一信息需求，换互补表述（同义/相关概念），避免重复微调原句与话题漂移。",
        ours=True,
        note_body=(
            "弱命中时原地改几个字再搜通常无效；换互补词面扩大召回，且不加额外改写模型。"
            "RET-9 N≥2 后丢刀已回滚该互补文案（§13.8）；本框描述的是历史尝试位，现行默认不再依赖第二搜互补词面提分。"
        ),
    )

    title8 = "8. 回到 AgentEngine 循环"
    body8 = "tool_result 写入 messages → checkpoint → 再次 assemble。之后普通工具结果仍可能被上下文预算截断。"
    h = step_h(draw, bw, title8, body8, ours=False)
    draw_step(draw, bx, cy, bw, title8, body8)
    cy += h + 24

    fy = footer(
        draw,
        max(cy, right_y) + 12,
        W,
        "先当「现行说明书」从上到下读完。只有带橙角标的步骤，才是我们优化后并进现行流程的；"
        "右侧说明为何加入、测下来站不站得住——不是另一套流程。",
    )
    return save(img, "retrieval-tuning-flowchart.png", fy)


def fig_context() -> Path:
    W, H = 1560, 2400
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    y0 = header(
        draw,
        W,
        "当前上下文 / 阅读流程（agent · read_file）",
        "整图是 agent 场景现在真实的读材料循环。橙角标 = 已进入现行流程的优化点；右侧说明加入原因与是否有效。",
    )

    frame_l, frame_pad = 48, 16
    bx, bw = frame_l + frame_pad, 500
    nx, nw = 860, 650
    cx = bx + bw // 2
    cy = y0 + 48
    loop_top = cy - 22
    right_y = y0 + 48
    frame_r = bx + bw + frame_pad  # while-frame right edge (spine only)

    def place_step(title, body, *, kind="step", ours=False, note_body: str | None = None):
        nonlocal cy, right_y
        h = step_h(draw, bw, title, body, ours=ours)
        if note_body:
            nh = note_h(draw, nw, note_body)
            draw_step(draw, bx, cy, bw, title, body, kind=kind, ours=ours)
            ny = max(cy, right_y)
            draw_note(draw, nx, ny, nw, note_body)
            row = max(h, (ny + nh) - cy)
            right_y = ny + nh + NOTE_GAP
        else:
            draw_step(draw, bx, cy, bw, title, body, kind=kind, ours=ours)
            row = h
        bottom = cy + row
        v_arrow(draw, cx, bottom, bottom + GAP)
        cy = bottom + GAP

    place_step(
        "1. ContextEngine.assemble",
        "组装 system、历史 messages、工具定义；含折叠与压缩。",
    )
    place_step(
        "2. 给「最近一次 read」更大组装预算",
        "普通 tool_result 约 4k；最近一次 read_file 约 32k；裁剪时优先保护最新读环。",
        ours=True,
        note_body=(
            "长文若与普通工具结果同等截断，模型等于没读到。只抬高当前工作集，是现行默认。"
            "可行且必要——后面所有读法都建立在「当前证据进得了窗」。"
        ),
    )
    place_step(
        "3. ModelGateway.stream",
        "流式输出；可中途取消。",
        kind="model",
    )

    dh = 80
    diamond(draw, cx, cy + dh // 2, 200, dh, "有 tool_use？")
    # keep NO-chip INSIDE the while-frame (to the right of the diamond)
    tip = cx + 100
    chip_l = tip + 10
    chip_r = frame_r - 12
    chip_y = cy + 14
    rr(draw, (chip_l, chip_y, chip_r, chip_y + 52), 8, fill=GRAY_FILL, outline=BORDER, width=1)
    draw.line((tip, cy + dh // 2, chip_l, cy + dh // 2), fill=INK, width=2)
    draw.text((chip_l + 12, chip_y + 10), "否 → 终答", fill=MUTED, font=F(12))
    draw.text((chip_l + 12, chip_y + 30), "结束本 Turn", fill=MUTED, font=F(12))

    info_y = max(cy, right_y)
    right_y = (
        draw_info(
            draw,
            nx,
            info_y,
            nw,
            "终答出口（流程原有）",
            "无工具调用时直接结束 Turn。橙角标步骤不改变这一出口，只改变窗内内容与答题形态。",
        )
        + NOTE_GAP
    )

    v_arrow(draw, cx, cy + dh, cy + dh + GAP)
    yes = "是"
    yx = cx + 14
    yy = cy + dh + 4
    draw.rectangle((yx - 4, yy - 2, yx + tw(draw, yes, F(12)) + 8, yy + 18), fill=BG)
    draw.text((yx, yy), yes, fill=MUTED, font=F(12))
    cy = cy + dh + GAP

    place_step(
        "4. 执行 read_file / grep …",
        "只读工具可并行。读文件按窗口切片；若未读完，返回 next_offset。",
    )
    place_step(
        "5. 截断时写明已读进度与续读位置",
        "提示中带已读长度、文件总长、建议 offset，避免静默截断。",
        ours=True,
        note_body=(
            "模型不知道窗外还有内容时会早停或瞎猜。把未读完变成工具事实。"
            "可行；拿掉续读纪律后放弃变多 → 留在现行流程。"
        ),
    )
    place_step(
        "6. 完成事件附带读取覆盖信息",
        "tool.completed 写入 chars_read / file_chars / next_offset 等轻量字段（不上全文）。",
        ours=True,
        note_body=(
            "没有覆盖信号就无法区分「没读」和「读了答错」。"
            "可行；提升可观测与归因，不直接改变答题分数。"
        ),
    )
    place_step(
        "7. tool_result 回灌 → checkpoint",
        "写回 messages，同 run 检查点，回到循环顶部再次 assemble。",
    )

    # Step 8 is a cross-cutting convention (not a sequential hop after 7).
    # Stop the spine arrow before it; associate with a short label.
    title8 = "8. 贯穿全程的读法 / 答题约定（system）"
    body8 = (
        "用户要短答则终答严格短答；长文未找到前优先续读；超长可先 grep 再定向读；"
        "附最小好/坏短答示例抑制套话；"
        "长材料：先摘 1–3 句支撑引文再答（CTX-8），终答优先沿用原文词面。"
    )
    note8 = (
        "预算解决「看得见」，约定解决「怎么读/怎么答」。"
        "CTX-8（2026-08-05）文案已进 agent/system.md：Evidence-before-answer + prefer passage wording；"
        "打 wrong_answer / 多跳证据丢失。free N≥2 仍为停机线第二票（勿与 RET-4 同批观测）。"
        "短答与示例压冗长，但更短≠更准——格式纪律保留，不当准确率银弹。"
    )
    h = step_h(draw, bw, title8, body8, ours=True)
    nh = note_h(draw, nw, note8)
    # slight vertical gap after last spine arrow target area
    draw_step(draw, bx, cy, bw, title8, body8, ours=True)
    ny = max(cy, right_y)
    draw_note(draw, nx, ny, nw, note8)
    cy = cy + max(h, (ny + nh) - cy) + 20
    right_y = ny + nh + NOTE_GAP

    loop_bottom = cy + 12
    rr(draw, (frame_l, loop_top, frame_r, loop_bottom), 14, fill=None, outline=STEP, width=2)
    lab = "AgentEngine while（现行循环边界）"
    lw = tw(draw, lab, F(12, bold=True)) + 18
    lab_y = loop_top - 18
    draw.rectangle((frame_l + 10, lab_y - 2, frame_l + 10 + lw, lab_y + 16), fill=BG)
    draw.text((frame_l + 16, lab_y), lab, fill=STEP, font=F(12, bold=True))

    fy = footer(
        draw,
        max(loop_bottom, right_y) + 22,
        W,
        "先整图当现行流程看。只有「我们加的」步骤才是优化进入现行链路的位置；"
        "右侧是原理与是否有效，不是另一套流程。",
    )
    return save(img, "context-tuning-flowchart.png", fy)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig_retrieval()
    fig_context()


if __name__ == "__main__":
    main()
