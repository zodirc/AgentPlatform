#!/usr/bin/env python3
"""Generate writing continuity diagram under docs/assets/writing/.

Run: python3 scripts/gen_writing_flowcharts.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "writing"

FONT_REG = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"
FONT_MED = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Medium.ttc"
FONT_BOLD = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc"

BG = (248, 249, 251)
INK = (24, 28, 36)
MUTED = (70, 78, 92)
LINE = (200, 205, 214)
ACCENT = (30, 90, 160)
ACCENT_SOFT = (226, 236, 248)
OK = (24, 110, 72)
OK_SOFT = (226, 242, 232)
WARN = (150, 85, 18)
WARN_SOFT = (255, 242, 220)
PURPLE = (85, 55, 140)
PURPLE_SOFT = (236, 230, 248)
CARD = (255, 255, 255)
BORDER = (205, 210, 218)


def font(size: int, *, bold: bool = False, medium: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else (FONT_MED if medium else FONT_REG)
    try:
        return ImageFont.truetype(path, size=size, index=0)
    except OSError:
        fallback = ROOT / "docs" / "assets" / "fonts" / "wqy-microhei.ttc"
        try:
            return ImageFont.truetype(str(fallback), size=size, index=0)
        except OSError:
            return ImageFont.load_default()


def new_img(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (w, h), BG)
    return img, ImageDraw.Draw(img)


def tw(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont) -> int:
    b = draw.textbbox((0, 0), text, font=f)
    return b[2] - b[0]


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.ImageFont, max_w: int) -> list[str]:
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


def title_block(draw: ImageDraw.ImageDraw, w: int, title: str, subtitle: str) -> int:
    draw.text((40, 28), title, fill=INK, font=font(28, bold=True))
    for i, line in enumerate(wrap(draw, subtitle, font(14), w - 80)):
        draw.text((40, 68 + i * 20), line, fill=MUTED, font=font(14))
    y = 68 + max(1, len(wrap(draw, subtitle, font(14), w - 80))) * 20 + 10
    draw.line((40, y, w - 40, y), fill=LINE, width=1)
    return y + 18


def card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    title: str,
    body: str,
    *,
    fill=CARD,
    outline=BORDER,
    title_color=INK,
) -> int:
    ft = font(16, medium=True)
    fb = font(13)
    tlines = wrap(draw, title, ft, w - 28)
    blines = wrap(draw, body, fb, w - 28)
    h = 18 + len(tlines) * 22 + 8 + len(blines) * 18 + 16
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=fill, outline=outline, width=2)
    ty = y + 12
    for line in tlines:
        draw.text((x + 14, ty), line, fill=title_color, font=ft)
        ty += 22
    ty += 4
    for line in blines:
        draw.text((x + 14, ty), line, fill=INK, font=fb)
        ty += 18
    return y + h + 12


def footer(draw: ImageDraw.ImageDraw, y: int, w: int, lines: list[str]) -> int:
    for i, line in enumerate(lines):
        draw.text((40, y + i * 18), line, fill=MUTED, font=font(12))
    return y + len(lines) * 18 + 8


def save(img: Image.Image, name: str, bottom: int) -> Path:
    path = OUT / name
    h = min(img.height, bottom + 32)
    img.crop((0, 0, img.width, h)).save(path, "PNG", optimize=True)
    return path


def fig_continuity() -> Path:
    W, H = 1400, 1550
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "写作 · 剧情衔接与大纲约束",
        "draft_section → drafts/ 树可见 · 正式稿另升。大纲进 Rules 前缀（截断），不是 System prompt。",
    )

    y = card(
        draw,
        40,
        y,
        W - 80,
        "1. 磁盘文件（Work 根）",
        "· outline.md / AGENT.md — 全局约束与作品规矩（可进 Rules）\n"
        "· manuscript.md — 正式稿\n"
        "· drafts/ — 在编稿（树可见）\n"
        "· .agent/history/ — 内部历史（隐藏）",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y = card(
        draw,
        40,
        y,
        W - 80,
        "2. 上下文注入（两条通道，勿混）",
        "Rules（project_context）：\n"
        "  读取 AGENT.md → agent.md → outline.md → AGENTS.md；共用约 2000 字；"
        "截断前缀常驻，UsageMeter 显示为 Rules。\n"
        "Writing ctx（volatile）：\n"
        "  cards / work index / focus·上章尾 / plan 相位等 — 按 Turn 易变，不焊进 system。\n"
        "完整长大纲仍靠 read_file；勿假设整本 outline 永远在窗里。",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = card(
        draw,
        40,
        y,
        W - 80,
        "3. 本轮工作面（Writing ctx 侧）",
        "· TOC / 本章位置与邻章\n"
        "· focus：本节目标与约束\n"
        "· 上章尾：衔接锚点",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    y = card(
        draw,
        40,
        y,
        W - 80,
        "4. 能力",
        "· draft_section — 只写 drafts/，不直接改正式稿\n"
        "· propose_patch — 升正式稿（可审 diff）\n"
        "· read_file — 需要细节时读磁盘（含超预算的 outline 全文）",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y = card(
        draw,
        40,
        y,
        W - 80,
        "5. 用户：文件树 / Diff",
        "树中打开在编稿；Diff 对比在编 vs 正式稿。UI Context Usage 中 Rules 有值才显示条。",
        fill=CARD,
    )
    y += 4
    y = footer(
        draw,
        y,
        W,
        [
            "代码：context/project.py · writing/focus.py · writing/cards.py",
            "对照：docs/assets/context/context-usage-layers-zh.png",
        ],
    )
    return save(img, "writing-continuity-outline-flow.png", y)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "writing-continuity-outline-flow.png"
    if target.exists():
        target.unlink()
    p = fig_continuity()
    im = Image.open(p)
    print(f"wrote {p.name}  {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()
