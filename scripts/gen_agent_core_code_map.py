#!/usr/bin/env python3
"""Generate a detailed PNG map of Agent Platform *core code* (not product flow).

Output: docs/assets/core/agent-core-code.png
Run: python3 scripts/gen_agent_core_code_map.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "core"
OUT_FILE = OUT / "agent-core-code.png"

FONT_REG = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc"
FONT_MED = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Medium.ttc"
FONT_BOLD = "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Bold.ttc"

BG = (246, 247, 250)
INK = (22, 26, 34)
MUTED = (72, 80, 94)
LINE = (198, 204, 214)
CARD = (255, 255, 255)
BORDER = (200, 206, 216)

CORE = (28, 86, 150)
CORE_SOFT = (224, 236, 248)
ENG = (24, 108, 78)
ENG_SOFT = (226, 242, 232)
CTX = (120, 70, 20)
CTX_SOFT = (255, 242, 220)
TOOL = (90, 50, 140)
TOOL_SOFT = (236, 230, 248)
STATE = (140, 45, 55)
STATE_SOFT = (255, 232, 234)
PROF = (50, 100, 120)
PROF_SOFT = (230, 242, 246)
GATE = (70, 70, 90)
GATE_SOFT = (236, 238, 242)


def font(size: int, *, bold: bool = False, medium: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_BOLD if bold else (FONT_MED if medium else FONT_REG)
    try:
        return ImageFont.truetype(path, size=size, index=0)
    except OSError:
        return ImageFont.load_default()


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


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill, outline, r: int = 10) -> None:
    draw.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=1)


def card(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    title: str,
    lines: list[str],
    accent,
    soft,
    title_size: int = 15,
    body_size: int = 12,
) -> None:
    rounded(draw, (x, y, x + w, y + h), CARD, BORDER, 12)
    draw.rectangle((x, y, x + 6, y + h), fill=accent)
    ft = font(title_size, bold=True)
    fb = font(body_size)
    draw.text((x + 16, y + 10), title, fill=INK, font=ft)
    yy = y + 34
    for line in lines:
        for wrapped in wrap(draw, line, fb, w - 28):
            draw.text((x + 16, yy), wrapped, fill=MUTED, font=fb)
            yy += body_size + 4
        yy += 2


def chip(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, soft, accent) -> int:
    f = font(11, medium=True)
    pad_x, pad_y = 8, 4
    w = tw(draw, text, f) + pad_x * 2
    h = 11 + pad_y * 2
    rounded(draw, (x, y, x + w, y + h), soft, accent, 8)
    draw.text((x + pad_x, y + pad_y - 1), text, fill=accent, font=f)
    return w + 6


def arrow_down(draw: ImageDraw.ImageDraw, x: int, y0: int, y1: int) -> None:
    draw.line((x, y0, x, y1 - 8), fill=LINE, width=2)
    draw.polygon([(x, y1), (x - 5, y1 - 8), (x + 5, y1 - 8)], fill=CORE)


def arrow_right(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int) -> None:
    draw.line((x0, y, x1 - 8, y), fill=LINE, width=2)
    draw.polygon([(x1, y), (x1 - 8, y - 5), (x1 - 8, y + 5)], fill=CORE)


def section_label(draw: ImageDraw.ImageDraw, x: int, y: int, text: str) -> None:
    draw.text((x, y), text, fill=INK, font=font(18, bold=True))


def main() -> None:
    W, H = 2200, 3000
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Header
    draw.rectangle((0, 0, W, 110), fill=(255, 255, 255))
    draw.line((0, 110, W, 110), fill=LINE, width=1)
    draw.text((48, 28), "Agent Platform · 核心代码地图（文件内关键代码）", fill=INK, font=font(28, bold=True))
    draw.text(
        (48, 68),
        "范围：runtime 核心环 · 不含 api/web/ops 派生层 · 路径均相对 services/runtime/app/",
        fill=MUTED,
        font=font(14),
    )

    # ===== Section A: constellation =====
    section_label(draw, 48, 130, "A. 核心文件星座（谁依赖谁）")
    files = [
        (48, 175, 340, 150, "engine/state.py", ["TurnState · Usage", "messages[] 是唯一记忆", "step_count / max_steps", "usage · cancelled · plan_phase", "read_registry · volatile_context"], STATE, STATE_SOFT),
        (420, 175, 400, 150, "engine/agent_engine.py", ["class AgentEngine ★", "run(state) 冻结 while", "_run_tool_batch / _run_tool", "_scoped_openai_tools", "挂 gateway + ContextEngine"], ENG, ENG_SOFT),
        (850, 175, 400, 150, "context/engine.py", ["ContextEngine.assemble_async", "_build_envelope 压窗流水线", "ToolExecutor.run", "审批门 · schema · timeout", "注入 scenario_id 等 kwargs"], CTX, CTX_SOFT),
        (1280, 175, 380, 150, "model/gateway.py", ["ModelGateway.stream", "yield str | StreamActivity", "| ModelResponse", "tool_calls / usage", "providers 可替换"], GATE, GATE_SOFT),
        (1700, 175, 440, 150, "tools/ + scenarios/", ["bootstrap.build_registry", "ToolSpec{name,handler,…}", "profiles/*.yaml 白名单", "*/system.md 系统提示", "registry.ScenarioProfile"], TOOL, TOOL_SOFT),
    ]
    for x, y, w, h, title, lines, accent, soft in files:
        card(draw, x, y, w, h, title=title, lines=lines, accent=accent, soft=soft, title_size=14, body_size=11)

    # dependency arrows under constellation
    y_arr = 340
    draw.text((48, y_arr), "依赖方向（结构）：", fill=MUTED, font=font(12, medium=True))
    deps = "TurnState ← AgentEngine → ContextEngine / ToolExecutor / Gateway    Profile → tool_scope → ToolSpec[] → AgentEngine    bootstrap.register → tools.core.tools handlers"
    draw.text((48, y_arr + 22), deps, fill=MUTED, font=font(12))

    # ===== Section B: AgentEngine.run =====
    section_label(draw, 48, 400, "B. AgentEngine.run — 单步核心代码骨架")
    draw.text(
        (48, 432),
        "文件 engine/agent_engine.py · while state.step_count < max_steps · 每步 finally → checkpoint",
        fill=MUTED,
        font=font(13),
    )

    step_boxes = [
        (48, 470, 250, 130, "① 步进门控", ["step_count += 1", "event: step.started", "预算 / cancel 检查", "stage_tool_scope(tools)"], ENG, ENG_SOFT),
        (330, 470, 310, 130, "② assemble_async", ["system + messages + tools", "压窗 / compact", "event: context.reported", "产出 messages[]"], CTX, CTX_SOFT),
        (670, 470, 340, 130, "③ gateway.stream", ["event: turn.thinking", "str → turn.token", "ModelResponse.tool_calls", "usage 累加"], GATE, GATE_SOFT),
        (1040, 470, 360, 130, "④ 分支", ["有 tool_calls → ⑤", "仅文本 → messages+=assistant", "final_summary=文本 · break", "budget / cancel 再判"], ENG, ENG_SOFT),
        (1430, 470, 360, 130, "⑤ _run_tool_batch", ["只读工具可并行", "写/exec 串行", "approval → return waiting", "结果写入 messages · continue"], TOOL, TOOL_SOFT),
        (1820, 470, 310, 130, "⑥ 步末 / 环末", ["_complete_step", "on_step_checkpoint", "cancelled / budget /", "max_steps / final"], STATE, STATE_SOFT),
    ]
    for x, y, w, h, title, lines, accent, soft in step_boxes:
        card(draw, x, y, w, h, title=title, lines=lines, accent=accent, soft=soft, title_size=14, body_size=11)
    for i in range(len(step_boxes) - 1):
        x0 = step_boxes[i][0] + step_boxes[i][2]
        x1 = step_boxes[i + 1][0]
        arrow_right(draw, x0 + 4, x1 - 4, 535)

    # loop note
    rounded(draw, (48, 620, 2152, 680), CORE_SOFT, CORE, 10)
    draw.text(
        (64, 638),
        "循环语义：④有工具 → ⑤执行后 continue（同 Turn 下一步）；④无工具 → break 出 while。waiting_approval 直接 return，由 controller 续跑。",
        fill=CORE,
        font=font(14, medium=True),
    )

    # ===== Section C: ContextEngine =====
    section_label(draw, 48, 720, "C. ContextEngine — assemble 内部流水线（context/engine.py）")
    ctx_steps = [
        (48, 770, 280, 160, "_build_envelope", ["复制 state.messages", "project + runtime + volatile", "fold stale read_file", "tool_result budget", "microcompact", "collapse / autocompact 标记"], CTX, CTX_SOFT),
        (360, 770, 280, 160, "可选 LLM compact", ["fingerprint 命中则复用", "precompact_cache 优先", "否则 summarize_via gateway", "（硬路径可关）"], CTX, CTX_SOFT),
        (672, 770, 280, 160, "_finalize_envelope", ["last_budget_report", "last_compaction_trace", "fill_ratio / tokens_*"], CTX, CTX_SOFT),
        (984, 770, 280, 160, "_materialize_messages", ["system 消息", "+ project/runtime/volatile", "+ 历史 messages", "→ 交给 gateway"], CTX, CTX_SOFT),
        (1296, 770, 400, 160, "ToolExecutor.run（同文件）", ["查 ToolSpec", "requires_approval？", "ops_eval / sticky 跳过", "validate_tool_arguments", "handler(**args, scenario_id=…)", "wait_for(timeout_s)"], TOOL, TOOL_SOFT),
        (1728, 770, 400, 160, "压窗策略协作", ["context/policy.py", "CompactionPolicy", "window / fill_collapse", "reserve_tokens", "compact_summarizer.py", "precompact_cache.py"], PROF, PROF_SOFT),
    ]
    for x, y, w, h, title, lines, accent, soft in ctx_steps:
        card(draw, x, y, w, h, title=title, lines=lines, accent=accent, soft=soft, title_size=13, body_size=11)
    for xs in [(328, 360), (640, 672), (952, 984)]:
        arrow_right(draw, xs[0], xs[1], 850)

    # ===== Section D: tools =====
    section_label(draw, 48, 970, "D. 工具核 — bootstrap / registry / tools.core（能力表）")
    card(
        draw,
        48,
        1020,
        520,
        220,
        title="tools/registry.py · ToolSpec",
        lines=[
            "name / description / parameters",
            "handler: async (**kwargs) → dict",
            "requires_approval · timeout_s",
            "ON_WRITE_TOOLS · sticky 集合",
            "ToolRegistry.register / list_for_names",
        ],
        accent=TOOL,
        soft=TOOL_SOFT,
    )
    card(
        draw,
        600,
        1020,
        720,
        220,
        title="tools/bootstrap.py · build_registry() + tool_scope(profile)",
        lines=[
            "注册全集 ToolSpec → handler 指向 tools.core.*",
            "tool_scope(profile)：按 ScenarioProfile.tool_names 过滤",
            "approval_overrides 覆盖 requires_approval",
            "stage_tool_scope：按 step/delivery 阶段性收窄工具面",
            "主工具：read/list/glob/grep · write/edit/rename · search_sources/codebase",
            "propose_patch/apply · draft_section · update_plan/outline · run_command/tests",
            "delegate · remember/recall · search_records · enrich_ioc…",
        ],
        accent=TOOL,
        soft=TOOL_SOFT,
    )
    card(
        draw,
        1350,
        1020,
        780,
        220,
        title="tools/core/tools.py · handler 肉身（节选）",
        lines=[
            "工作区路径 / 租户可见性守卫",
            "read_file / write_file / edit_file / grep / glob",
            "search_sources → retrieval.store（Index 平面入口）",
            "search_codebase · sync_sources_index",
            "draft_section / propose_patch / export_document",
            "run_command → shell/sandbox（bwrap）",
            "其余：intel_enrich / memory / records…",
        ],
        accent=TOOL,
        soft=TOOL_SOFT,
    )

    # ===== Section E: Profile =====
    section_label(draw, 48, 1280, "E. ScenarioProfile — 核心环上的唯一合法扩展旋钮")
    card(
        draw,
        48,
        1330,
        680,
        200,
        title="scenarios/registry.py",
        lines=[
            "@dataclass ScenarioProfile",
            "scenario_id · display_name",
            "system_prompt（或 template→system.md）",
            "tool_names[] · max_steps",
            "approval_overrides · retrieval{}",
            "subagent_types · workspace/web_layout",
            "ScenarioRegistry.load(profiles/*.yaml)",
        ],
        accent=PROF,
        soft=PROF_SOFT,
    )
    card(
        draw,
        760,
        1330,
        680,
        200,
        title="profiles/agent.yaml（例）",
        lines=[
            "system_prompt_template: agent/system.md",
            "tool_names: read/write/edit/grep/…",
            "run_command · run_tests · delegate…",
            "max_steps: 50",
            "approval_overrides: write always",
            "workspace_layout: repository",
        ],
        accent=PROF,
        soft=PROF_SOFT,
    )
    card(
        draw,
        1470,
        1330,
        660,
        200,
        title="接到核心的方式",
        lines=[
            "controller 取 profile.system_prompt",
            "tool_scope(profile, registry) → ToolSpec[]",
            "AgentEngine(tools=…, system_prompt=…)",
            "Engine 不 if scenario == …",
            "retrieval.scenario_scope 读 profile.retrieval",
            "handler 收到 scenario_id kwargs",
        ],
        accent=PROF,
        soft=PROF_SOFT,
    )

    # ===== Section F: TurnState detail =====
    section_label(draw, 48, 1570, "F. TurnState 字段核（engine/state.py）— 循环读写的全部状态")
    fields = [
        ("身份", "turn_id session_id run_id trace_id scenario_id", STATE_SOFT, STATE),
        ("记忆", "messages: list[dict]  （user/assistant/tool 块）", ENG_SOFT, ENG),
        ("步进", "step_count · max_steps · termination_reason", CORE_SOFT, CORE),
        ("预算", "usage.input/output_tokens · budget_exceeded", CTX_SOFT, CTX),
        ("控制", "cancelled · cancel_force · ops_eval · model_mode", GATE_SOFT, GATE),
        ("计划", "plan_hint · plan_phase · delivery · volatile_context", PROF_SOFT, PROF),
        ("审批粘性", "writes_preapproved · exec_preapproved", TOOL_SOFT, TOOL),
        ("读守卫", "read_registry: path → PathReadState", STATE_SOFT, STATE),
    ]
    x = 48
    y = 1620
    for title, body, soft, accent in fields:
        f = font(12, bold=True)
        fb = font(12)
        w = max(tw(draw, title, f), tw(draw, body, fb)) + 28
        h = 58
        if x + w > W - 48:
            x = 48
            y += 70
        rounded(draw, (x, y, x + w, y + h), soft, accent, 8)
        draw.text((x + 12, y + 8), title, fill=accent, font=f)
        draw.text((x + 12, y + 30), body, fill=MUTED, font=fb)
        x += w + 12

    # ===== Section G: call stack =====
    section_label(draw, 48, 1800, "G. 一次工具调用的代码栈（从循环到 handler）")
    stack = [
        (48, 1850, "AgentEngine.run", "发现 tool_calls"),
        (280, 1850, "_run_tool_batch", "只读并行 / 写串行"),
        (540, 1850, "_run_tool", "cache · 事件 · 护栏"),
        (800, 1850, "ToolExecutor.run", "审批 · validate · timeout"),
        (1080, 1850, "ToolSpec.handler", "tools.core.tools.*"),
        (1380, 1850, "（可选）retrieval/store", "search_sources 热路径"),
        (1700, 1850, "回写 tool_result", "messages += · continue"),
    ]
    for i, (x, y, title, sub) in enumerate(stack):
        rounded(draw, (x, y, x + 220, y + 70), CARD, BORDER, 10)
        draw.text((x + 12, y + 12), title, fill=INK, font=font(13, bold=True))
        draw.text((x + 12, y + 38), sub, fill=MUTED, font=font(11))
        if i < len(stack) - 1:
            arrow_right(draw, x + 224, stack[i + 1][0] - 4, y + 35)

    # ===== Section H: what is NOT core =====
    section_label(draw, 48, 1960, "H. 明确不在核心环内（派生层，勿与上图混淆）")
    noncore = [
        "turn_controller.py — 安装座：Session/Turn/审批续跑/落事件",
        "graph/runner.py — LangGraph 单节点透传",
        "api/routers · projection · SSE — 控制面与读模型",
        "web/workbench · ops/* — UI 派生",
        "scripts/official_bench · official_agent_path — 温度计",
        "deploy/* — 包装",
    ]
    xx, yy = 48, 2010
    for t in noncore:
        w = chip(draw, xx, yy, t, GATE_SOFT, GATE)
        xx += w
        if xx > W - 200:
            xx = 48
            yy += 36

    # ===== Section I: read order =====
    section_label(draw, 48, 2120, "I. 精读顺序（只读核心代码）")
    order = [
        ("1", "state.py", "先看状态长什么样"),
        ("2", "agent_engine.run", "再看 while 一步"),
        ("3", "assemble_async", "窗口如何组装"),
        ("4", "ToolExecutor.run", "工具如何被调用"),
        ("5", "bootstrap + tools.py", "有哪些手、手干什么"),
        ("6", "profiles + system.md", "如何换皮"),
        ("7", "gateway.stream", "模型如何进环"),
    ]
    ox = 48
    for n, title, hint in order:
        rounded(draw, (ox, 2170, ox + 280, 2170 + 90), CARD, BORDER, 12)
        draw.ellipse((ox + 14, 2184, ox + 42, 2212), fill=CORE_SOFT, outline=CORE)
        draw.text((ox + 22, 2188), n, fill=CORE, font=font(14, bold=True))
        draw.text((ox + 52, 2184), title, fill=INK, font=font(14, bold=True))
        draw.text((ox + 52, 2214), hint, fill=MUTED, font=font(12))
        if ox < 48 + 280 * 6:
            arrow_right(draw, ox + 284, ox + 300, 2215)
        ox += 300

    # ===== Code excerpt panel =====
    section_label(draw, 48, 2300, "J. 核心伪代码（对齐真实符号名）")
    rounded(draw, (48, 2350, 2152, 2920), (28, 30, 38), (28, 30, 38), 12)
    code = """# engine/agent_engine.py
async def run(self, state: TurnState) -> str | None:
    while state.step_count < state.max_steps:
        if budget/cancel: break
        state.step_count += 1
        tools = stage_tool_scope(self._tool_specs, step_count=..., delivery=...)
        messages = await self._context.assemble_async(system_prompt, state, gateway, tools, volatile)
        # write context.reported
        async for chunk in self._gateway.stream(messages, tools):
            # str → turn.token ; StreamActivity → thinking.delta ; ModelResponse → tool_calls/usage
        if tool_calls:
            state.messages.append(assistant_tool_uses(tool_calls, text))
            outcome = await self._run_tool_batch(tool_calls, state, ...)
            if outcome == "waiting_approval": return "waiting_approval"
            continue
        if response_text:
            state.messages.append(assistant_text(response_text)); break
        # finally: _complete_step + on_step_checkpoint(state)

# context/engine.py
ToolExecutor.run → (approval? validate?) → await spec.handler(**args, scenario_id=state.scenario_id)
ContextEngine.assemble_async → _build_envelope(fold/budget/micro/collapse) → compact? → materialize

# tools/bootstrap.py
build_registry() 注册 ToolSpec;  tool_scope(profile) 按 tool_names 切片;  handler 在 tools/core/tools.py

# scenarios/registry.py
ScenarioProfile(system_prompt, tool_names, max_steps, approval_overrides, retrieval) ← profiles/*.yaml"""
    mono = font(13)
    cy = 2368
    for line in code.split("\n"):
        color = (180, 190, 210) if line.startswith("#") or not line.strip() else (220, 225, 235)
        if line.strip().startswith("async def") or line.strip().startswith("ToolExecutor") or line.strip().startswith("ContextEngine") or line.strip().startswith("build_registry") or line.strip().startswith("ScenarioProfile"):
            color = (140, 200, 255)
        draw.text((72, cy), line, fill=color, font=mono)
        cy += 18

    # Footer
    draw.text(
        (48, 2940),
        "生成：scripts/gen_agent_core_code_map.py · 与实现漂移时以源码为准",
        fill=MUTED,
        font=font(12),
    )

    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT_FILE, format="PNG", optimize=True)
    print(f"wrote {OUT_FILE} ({OUT_FILE.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
