#!/usr/bin/env python3
"""Generate Chinese context-window diagrams under docs/assets/context/.

Aligns with UsageMeter (Cursor-style labels) and ContextEngine wire layout.
Run: python3 scripts/gen_context_flowcharts.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "context"

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
DANGER = (150, 45, 45)
DANGER_SOFT = (255, 232, 232)
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
    title_size: int = 16,
) -> int:
    ft = font(title_size, medium=True)
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


def banner(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, text: str, fill) -> int:
    h = 36
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=fill, outline=BORDER)
    draw.text((x + 14, y + 8), text, fill=INK, font=font(15, medium=True))
    return y + h + 12


def v_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, gap: int = 14) -> int:
    draw.line((x, y, x, y + gap), fill=ACCENT, width=3)
    draw.polygon([(x - 6, y + gap - 2), (x + 6, y + gap - 2), (x, y + gap + 8)], fill=ACCENT)
    return y + gap + 16


def footer(draw: ImageDraw.ImageDraw, y: int, w: int, lines: list[str]) -> int:
    for i, line in enumerate(lines):
        draw.text((40, y + i * 18), line, fill=MUTED, font=font(12))
    return y + len(lines) * 18 + 8


def save(img: Image.Image, name: str, bottom: int) -> Path:
    path = OUT / name
    h = min(img.height, bottom + 32)
    img.crop((0, 0, img.width, h)).save(path, "PNG", optimize=True)
    return path


def fig_usage_layers() -> Path:
    W, H = 1400, 1750
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "上下文 · Usage 分层（UI ↔ 请求）",
        "与工作台 Context Usage / UsageMeter 同名；与 ContextEngine 物化顺序一致。Skills/Subagent 本平台不单独计量。",
    )

    rows = [
        (
            ACCENT_SOFT,
            ACCENT,
            "System prompt",
            "请求：system 文本 ← 场景 system.md（角色、红线、跨工具工作流）。"
            "不含各工具 how-to/schema。跨 Step 应力求字节稳定（prompt cache）。",
        ),
        (
            PURPLE_SOFT,
            PURPLE,
            "Tool definitions",
            "请求：tools[] ← name + description(how-to) + input_schema。"
            "与 System prompt 分层；默认 schema 静态，晚期禁用走运行时闸。",
        ),
        (
            OK_SOFT,
            OK,
            "Rules",
            "请求：[project_context] user ← Work 根 AGENT.md / agent.md / outline.md / AGENTS.md。"
            "共用约 2000 字预算；不焊进 system。小说 outline 截断前缀常驻于此。",
        ),
        (
            WARN_SOFT,
            WARN,
            "Writing ctx · Runtime · Session",
            "Writing ctx=volatile（cards/focus/plan/seed 提醒…）；"
            "Runtime=step 等（必须垫在 Conversation 之后）；Session=会话侧注入（有才显示）。",
        ),
        (
            DANGER_SOFT,
            DANGER,
            "Conversation",
            "请求：messages 主体 = user + assistant + tool_results + compact 指针/摘要。"
            "卫生与 80/90/95 阶梯主要作用于此。UI 合并显示为 Conversation。",
        ),
    ]
    for fill, outline, t, body in rows:
        y = card(draw, 40, y, W - 80, t, body, fill=fill, outline=outline, title_color=outline)

    y = banner(draw, 40, y, W - 80, "物化顺序（发给 provider）", ACCENT_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "前缀稳 → 历史 → 易变垫底",
        "[1] System prompt  [2] Rules  [3] Writing ctx  [4] Conversation…  [5] Runtime\n"
        "+ Tool definitions 作为请求级 tools[]（不计在 messages 字符串内，UI 单独一条）\n"
        "禁止：把 cards/outline/step 焊进 system.md；禁止把 tools schema 写进 system 长文。",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y += 4
    y = footer(
        draw,
        y,
        W,
        [
            "代码：context/engine.py · context/project.py · scenarios/*/system.md · tools/bootstrap.py",
            "UI：services/web/.../UsageMeter.tsx · 心智：docs/learn/mental/context.md · 1.md §1",
        ],
    )
    return save(img, "context-usage-layers-zh.png", y)


def fig_fill_ratio() -> Path:
    W, H = 1400, 1650
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "填充率：窗口被什么占满了？",
        "fill = 估算占用 ÷ (model_window − output_reserve)。128K 档默认 reserve≈30000 → usable≈98000。",
    )

    y = banner(draw, 40, y, W - 80, "可用输入窗（UI Context Usage 分层）", ACCENT_SOFT)
    # stacked bar legend as cards in a row
    segs = [
        ("System prompt", "system.md", ACCENT_SOFT, ACCENT),
        ("Tool definitions", "tools[]", PURPLE_SOFT, PURPLE),
        ("Rules", "project ≈2k", OK_SOFT, OK),
        ("Writing/Runtime", "后置 user", WARN_SOFT, WARN),
        ("Conversation", "可压缩主体", (255, 228, 228), DANGER),
    ]
    bw = (W - 80 - 4 * 12) // 5
    bottoms = []
    for i, (lab, body, fill, outline) in enumerate(segs):
        bottoms.append(
            card(
                draw,
                40 + i * (bw + 12),
                y,
                bw,
                lab,
                body,
                fill=fill,
                outline=outline,
                title_color=outline,
                title_size=13,
            )
        )
    y = max(bottoms)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "右侧另有输出预留（不计入 usable）",
        "output_reserve_tokens 默认 30000（随窗口等比）。预留给模型生成，不算进填充率分母的「可塞输入」。",
        fill=DANGER_SOFT,
        outline=DANGER,
        title_color=DANGER,
    )
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "阈值阶梯（组窗当下 / 旁路）", WARN_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "看 fill，不要混成「每轮税」",
        "· ≈78% 软预压缩：Turn 结束后异步备 context_summary（不挡首 token；不在组窗当下折历史）\n"
        "· ≥80% collapse：Conversation 中间 → 指针；保留首条 user + 约 35% 热尾\n"
        "· ≥90% snip：删最旧完整消息组（可循环）；保护当前指令与最近 read_file\n"
        "· ≥95% autocompact：结构化摘要（优先吃 78% 缓存；默认同步 LLM 关）\n"
        "没有单独的 100% 档；硬闸约在 95%。阶梯主要动 Conversation，不是去删 tools[]。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y += 8
    y = footer(
        draw,
        y,
        W,
        [
            "settings：context_window_tokens / context_output_reserve_tokens / context_fill_*",
            "对照图：context-usage-layers-zh.png · context-hygiene-vs-ladder.png",
        ],
    )
    return save(img, "context-fill-ratio.png", y)


def fig_collapse_80() -> Path:
    W, H = 1400, 1100
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "≥80% 中间折叠：留开头 + 最近热区",
        "collapse 作用在 Conversation（messages）。System prompt / Tool definitions / Rules 前缀不在此「中间」刀里。",
    )

    left = card(
        draw,
        40,
        y,
        640,
        "折叠前（Conversation）",
        "开头：往往第一条 user（初始任务/硬约束）\n"
        "……中间大量历史（可读文件、多次 search…）……\n"
        "热区：自最新向前约 35% 可用消息预算的原文",
        fill=CARD,
    )
    right = card(
        draw,
        720,
        y,
        640,
        "折叠后",
        "开头保留\n"
        "[collapsed N earlier messages; …]\n"
        "热区原文保留\n\n"
        "中间换成指针，不是整窗摘要",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y = max(left, right)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "勿与 Rules 混淆",
        "· Rules（outline.md / AGENT.md）在 project 前缀 user，不是 collapse 的「开头」同义词。\n"
        "· 磁盘草稿与 Web 聊天记录通常不动；出窗 ≠ 文件没了。\n"
        "· 需要中间细节 → 再 read_file / search_sources。",
        fill=DANGER_SOFT,
        outline=DANGER,
        title_color=DANGER,
    )
    y += 8
    y = footer(
        draw,
        y,
        W,
        ["代码：context/engine.py collapse · hot_zone_ratio=0.35"],
    )
    return save(img, "context-collapse-80.png", y)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Only replace the diagrams this script owns (keep hygiene / full-pipeline / snip if still hand-tuned OK)
    owned = {
        "context-usage-layers-zh.png",
        "context-fill-ratio.png",
        "context-collapse-80.png",
    }
    for name in owned:
        p = OUT / name
        if p.exists():
            p.unlink()
            print("deleted", name)
    paths = [fig_usage_layers(), fig_fill_ratio(), fig_collapse_80()]
    for p in paths:
        im = Image.open(p)
        print(f"wrote {p.name}  {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()
