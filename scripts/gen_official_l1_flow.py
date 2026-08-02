#!/usr/bin/env python3
"""Generate Chinese L1 official-bench agent-path flow diagram (PNG).

Run (if system Pillow missing, use extracted deps as in CI notes):
  PYTHONPATH=... LD_LIBRARY_PATH=... python3 scripts/gen_official_l1_flow.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "ops"
FONT_PATH = ROOT / "docs" / "assets" / "fonts" / "wqy-microhei.ttc"

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
DANGER = (150, 45, 45)
DANGER_SOFT = (255, 232, 232)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size=size)


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
    title_size: int = 15,
    body_size: int = 13,
    line_h: int = 20,
) -> int:
    ft = font(title_size)
    fb = font(body_size)
    tlines = wrap(draw, title, ft, w - 28)
    blines = wrap(draw, body, fb, w - 28)
    h = 12 + len(tlines) * 22 + 6 + len(blines) * line_h + 14
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=fill, outline=outline, width=2)
    ty = y + 10
    for line in tlines:
        draw.text((x + 14, ty), line, fill=title_color, font=ft)
        ty += 22
    ty += 4
    for line in blines:
        draw.text((x + 14, ty), line, fill=MUTED, font=fb)
        ty += line_h
    return y + h


def banner(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, text: str, fill) -> int:
    draw.rounded_rectangle((x, y, x + w, y + 30), radius=8, fill=fill, outline=fill)
    draw.text((x + 12, y + 5), text, fill=INK, font=font(14))
    return y + 40


def v_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, gap: int = 22) -> int:
    y1 = y + gap
    draw.line((x, y + 2, x, y1 - 8), fill=ACCENT, width=3)
    draw.polygon([(x - 6, y1 - 12), (x + 6, y1 - 12), (x, y1)], fill=ACCENT)
    return y1 + 4


def mini_box(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    title: str,
    lines: list[str],
    *,
    fill=CARD,
    outline=BORDER,
    title_color=INK,
) -> None:
    draw.rounded_rectangle((x, y, x + w, y + h), radius=8, fill=fill, outline=outline, width=2)
    draw.text((x + 10, y + 8), title, fill=title_color, font=font(13))
    ty = y + 30
    for line in lines:
        draw.text((x + 10, ty), line, fill=MUTED, font=font(11))
        ty += 16


def build() -> Path:
    W, H = 1600, 3200
    img, draw = new_img(W, H)
    OUT.mkdir(parents=True, exist_ok=True)

    # Title
    draw.text((40, 24), "官方小量 · L1 同构评测全流程（主 Agent 路径）", fill=INK, font=font(26))
    sub = (
        "协议戳记 official-small-2026-08-m2 · 入口：Ops「评测路径=L1 agent」或 make official-bench-*-agent"
        " · 文档：docs/topics/official-bench-agent-tuning.md"
    )
    for i, line in enumerate(wrap(draw, sub, font(13), W - 80)):
        draw.text((40, 62 + i * 18), line, fill=MUTED, font=font(13))
    y = 100
    draw.line((40, y, W - 40, y), fill=LINE, width=2)
    y += 16

    # Legend
    y = banner(draw, 40, y, W - 80, "读图约定：蓝=控制/编排 · 绿=产品主路径（与用户相同）· 橙=官方题集/指标 · 紫=产物与账本", ACCENT_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "核心原则（因果不可反）",
        "评测是温度计：官方题集必须经主 agent 真 Turn 计分。"
        "调优是工程：Harness / RAG / 预算 / 工具契约——不是为刷分改旁路。"
        "分数上升只是工程变好的间接结果。禁止 L0 旁路分冒充主指数。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y = v_arrow(draw, W // 2, y)

    # Phase 0 entry
    y = banner(draw, 40, y, W - 80, "① 启动入口（二选一，等价）", PURPLE_SOFT)
    col_w = (W - 100) // 2
    y0 = y
    h_left = card(
        draw,
        40,
        y0,
        col_w,
        "A. Ops 官方评测页",
        "打开 http://localhost/ops/<OPS_TEST_SECRET>/official\n"
        "勾选套件：检索 / 上下文 / 编码\n"
        "评测路径 =「L1 agent（主路径）」← 默认\n"
        "填写评测模型（上下文/编码必填；检索建议填）\n"
        "点「开始」→ POST /api/v1/ops/official/runs\n"
        "body.eval_path = \"agent\"",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    h_right = card(
        draw,
        60 + col_w,
        y0,
        col_w,
        "B. 主机 Make / CLI",
        "前置：make up · .env 含 OPS_TEST_SECRET · BENCH_MODEL_*\n"
        "建议先：make official-bench-pull（缓存题集）\n"
        "make official-bench-retrieval-agent   # QUERY_LIMIT=3 冒烟\n"
        "make official-bench-context-agent    # OFFICIAL_CONTEXT_LIMIT=2\n"
        "make official-bench-coding-infer-agent  # OFFICIAL_SWE_TIER=n3\n"
        "CLI 内部同样打 Ops API（eval_path=agent）",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    y = max(h_left, h_right)
    y = v_arrow(draw, W // 2, y)

    # API orchestration
    y = banner(draw, 40, y, W - 80, "② API 编排（控制面，不跑 loop）", ACCENT_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "services/api · official_runner → official_agent_path",
        "create_and_start(eval_path=agent) 在 api 进程内执行 L1（不派发 agent-bench）。\n"
        "日志特征：「L1 agent-path — product Session/Turn (not bench worker)」\n"
        "若选 L0 component：仍走独立 agent-bench（hybrid 直打 / 旁路 assemble / bench 直出 patch）— 仅对照。\n"
        "L1 与用户会话隔离：Work 建在 /data/ops-l1/<run_id>/…（agent_data 卷，runtime 可见）。",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = v_arrow(draw, W // 2, y)

    # Official datasets
    y = banner(draw, 40, y, W - 80, "③ 官方题集物化（Turn 外 · Index plane）", WARN_SOFT)
    box_w = (W - 120) // 3
    by = y
    mini_box(
        draw,
        40,
        by,
        box_w,
        150,
        "检索 · BEIR",
        [
            "SciFact / NFCorpus / FiQA",
            "pull → BENCH_DATA_DIR",
            "语料写入 Work/sources/beir/…",
            "每文档 <doc_id>.txt",
            "Turn 外 sync_sources_index",
            "（A9：查询路径禁止建库）",
        ],
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    mini_box(
        draw,
        50 + box_w,
        by,
        box_w,
        150,
        "上下文 · LongBench",
        [
            "multifieldqa / hotpotqa /",
            "narrativeqa 小切片",
            "passage → sources/passage.md",
            "问题进用户消息",
            "禁止：单条超长 user +",
            "直接 ContextEngine.assemble",
        ],
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    mini_box(
        draw,
        60 + 2 * box_w,
        by,
        box_w,
        150,
        "编码 · SWE-bench Lite",
        [
            "题集 instances + 档位切片",
            "默认锚点档 n25（冒烟 n3）",
            "problem.md 写入 Work",
            "scenario_id = agent",
            "补丁后可另跑 harness",
            "resolve（Docker）",
        ],
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y = by + 160
    y = v_arrow(draw, W // 2, y)

    # Main agent path - the heart
    y = banner(draw, 40, y, W - 80, "④ 主 Agent 交互路径（与用户相同 · 绿色主链）", OK_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "每一题 = 一次真实产品闭环",
        "创建 Session（绑定 L1 Work，visibility_seed=false）\n"
        "→ api create_turn + runtime StartTurn（ops_eval=true，可注入评测模型）\n"
        "→ TurnController Intake（确定性）→ AgentEngine while：\n"
        "      ContextEngine.assemble → ModelGateway → 工具（search_sources / read_file / propose_patch…）\n"
        "      → tool_result 回灌 → checkpoint → 写 turn_events\n"
        "→ 等终态（turn.completed / failed / cancelled）\n"
        "绝不：store.search 直打 · 单消息旁路 assemble · bench_model 一次性 chat 冒充主指数",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y = v_arrow(draw, W // 2, y, 18)

    # Three suite detail strips
    y = banner(draw, 40, y, W - 80, "⑤ 三套套件：题面如何进入主路径 · 如何打官方分", ACCENT_SOFT)
    suite_y = y
    sw = (W - 120) // 3
    suite_h = 280
    suites = [
        (
            "检索 L1",
            [
                "用户消息：引导调用",
                "search_sources(query, limit=k)",
                "模型在 Turn 内调工具",
                "事件：retrieval.completed",
                "  · hits 预览 + ranked≤100",
                "path → BEIR doc_id",
                "计 nDCG@k / R@k / MAP",
                "L2 探针：是否调用 search、",
                "工具名序列、turn_id",
            ],
        ),
        (
            "上下文 L1",
            [
                "材料已在 passage.md",
                "模型 read_file 和/或",
                "search_sources 多 Step",
                "ContextEngine 仅在 loop",
                "内每步 assemble",
                "终态抽取 assistant 答案",
                "与官方 gold 比 F1/EM",
                "主指标：agent_f1",
                "（非 truncate 竞赛）",
            ],
        ),
        (
            "编码 L1",
            [
                "读 problem.md",
                "探索 / 编辑工具链",
                "propose_patch → 事件",
                "patch.proposed 抽 diff",
                "写 predictions.jsonl",
                "主辅：patch_rate",
                "权威：harness resolve",
                "@同 fingerprint 档位",
                "（另步 Docker 评分）",
            ],
        ),
    ]
    for i, (title, lines) in enumerate(suites):
        mini_box(
            draw,
            40 + i * (sw + 10),
            suite_y,
            sw,
            suite_h,
            title,
            lines,
            fill=OK_SOFT,
            outline=OK,
            title_color=OK,
        )
    y = suite_y + suite_h + 8
    y = v_arrow(draw, W // 2, y)

    # Artifacts
    y = banner(draw, 40, y, W - 80, "⑥ 过程与结果落盘（可复现）", PURPLE_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "eval/reports/official/（默认不进 git）",
        "runs/<uuid>/process.jsonl · manifest.json · result.json · report.html\n"
        "latest_retrieval.json / latest_context.json / latest_coding.json · latest_run.json\n"
        "Ops 历史 suite=official 可打开；L1 带 eval_path=agent、protocol_version=m2\n"
        "对比：make official-bench-compare（须同协议 + 同 eval_path；编码还要同 tier/fingerprint）",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    y = v_arrow(draw, W // 2, y)

    # After eval - tuning loop
    y = banner(draw, 40, y, W - 80, "⑦ 评测之后才调优（工程票，不是改评测）", WARN_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "Phase B → C → D",
        "B 归因：用 turn_events 分桶（未搜 / hits 弱 / snip 打穿 / 不出 patch…）\n"
        "C 改生产：工具说明 · RAG Index · 预算/snip 地板 · 执行护栏（不改 AgentEngine while）\n"
        "D 同协议 L1 复测 → 速率门 + golden 不回归 → 才 update-baseline\n"
        "纪律：未完成诚实 L1 首跑与归因前，不开「宣称由 official 驱动」的工程优化 PR",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y = v_arrow(draw, W // 2, y)

    # Contrast L0
    y = banner(draw, 40, y, W - 80, "对照：L0 component（旧旁路，勿作主指数）", DANGER_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "何时仍有用",
        "排障检索库 IR、验证 pull/管线、与 L1 对照看「工具/交互」掉了多少分。\n"
        "路径：Ops 评测路径=L0 · 或 make official-bench-retrieval（无 --eval-path agent）。\n"
        "特征：agent-bench · store.search(hybrid) · 单消息 assemble · bench_model 直出 patch。",
        fill=DANGER_SOFT,
        outline=DANGER,
        title_color=DANGER,
    )
    y += 16

    # Footer
    draw.line((40, y, W - 40, y), fill=LINE, width=1)
    y += 12
    foot = [
        "速率红线：评测跑在 Ops/隔离 Work，不改用户热路径；禁止默认同步 CE / 每轮预检索 / 为刷分开旁路。",
        "重建服务后生效：make up-api && make up-web（或 make up）。冒烟务必加 QUERY_LIMIT / 小 context limit / n3。",
        f"生成脚本：scripts/gen_official_l1_flow.py · 输出：docs/assets/ops/official-l1-agent-path-flow-zh.png",
    ]
    for line in foot:
        draw.text((40, y), line, fill=MUTED, font=font(11))
        y += 18

    path = OUT / "official-l1-agent-path-flow-zh.png"
    img.crop((0, 0, W, min(H, y + 28))).save(path, "PNG", optimize=True)
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    return path


if __name__ == "__main__":
    build()
