#!/usr/bin/env python3
"""Generate Chinese RAG principle diagrams under docs/assets/rag/.

Focus: readable layout, current-system detail (chunking, ANN@10k+, hybrid, audit).
Run: python3 scripts/gen_rag_flowcharts.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "rag"

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
        return ImageFont.load_default()


def canvas(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    return Image.new("RGB", (w, h), BG), ImageDraw.Draw(Image.new("RGB", (w, h), BG))


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
    draw.line((40, y, w - 40, y), fill=LINE, width=2)
    return y + 18


def banner(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, text: str, fill) -> int:
    draw.rounded_rectangle((x, y, x + w, y + 32), radius=8, fill=fill, outline=fill)
    draw.text((x + 14, y + 6), text, fill=INK, font=font(15, medium=True))
    return y + 44


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
    body_size: int = 14,
    line_h: int = 22,
) -> int:
    ft = font(title_size, medium=True)
    fb = font(body_size)
    tlines = wrap(draw, title, ft, w - 28)
    blines = wrap(draw, body, fb, w - 28)
    h = 14 + len(tlines) * 24 + 8 + len(blines) * line_h + 16
    draw.rounded_rectangle((x, y, x + w, y + h), radius=10, fill=fill, outline=outline, width=2)
    ty = y + 12
    for line in tlines:
        draw.text((x + 14, ty), line, fill=title_color, font=ft)
        ty += 24
    ty += 6
    for line in blines:
        draw.text((x + 14, ty), line, fill=MUTED, font=fb)
        ty += line_h
    return y + h


def v_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, gap: int = 26) -> int:
    y1 = y + gap
    draw.line((x, y + 2, x, y1 - 8), fill=ACCENT, width=3)
    draw.polygon([(x - 6, y1 - 12), (x + 6, y1 - 12), (x, y1)], fill=ACCENT)
    return y1 + 6


def h_arrow(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int) -> None:
    draw.line((x0, y, x1 - 8, y), fill=ACCENT, width=3)
    draw.polygon([(x1 - 11, y - 6), (x1 - 11, y + 6), (x1, y)], fill=ACCENT)


def footer(draw: ImageDraw.ImageDraw, y: int, w: int, lines: list[str]) -> int:
    draw.line((40, y, w - 40, y), fill=LINE, width=1)
    ty = y + 10
    for line in lines:
        draw.text((40, ty), line, fill=MUTED, font=font(12))
        ty += 18
    return ty


def save(img: Image.Image, name: str, bottom: int) -> Path:
    path = OUT / name
    h = min(img.height, bottom + 32)
    img.crop((0, 0, img.width, h)).save(path, "PNG", optimize=True)
    return path


# ─── 01 two planes ───────────────────────────────────────────────────────────


def fig_two_planes() -> Path:
    W, H = 1400, 1200
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "01 · 两平面：索引面 vs 交互面",
        "当前系统的总骨架（docs/15）。对话热路径只读已有投影；建库 / 嵌入 / watch 永不进 Turn。",
    )
    y = banner(draw, 40, y, W - 80, "为什么要拆开", WARN_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "速率红线",
        "若在用户提问时同步切块+SentenceTransformer 嵌入（intel 首建可达上万 chunk、十余分钟），"
        "首 token 会被拖死。所以：目录是真相，索引是后台投影；search_sources 禁止 sync()。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y = v_arrow(draw, W // 2, y)

    left_x, right_x = 40, 720
    lw, rw = 640, 640
    top = y
    y_l = banner(draw, left_x, top, lw, "索引面（旁路 · 慢可以）", OK_SOFT)
    y_l = card(
        draw,
        left_x,
        y_l,
        lw,
        "做什么",
        "· 扫 sources/**（含 seed/intel）\n"
        "· Markdown 树切块 + 拼 embed 文本\n"
        "· 批嵌入（batch=64）写入 pgvector\n"
        "· 启动扫 / 目录 watch / 上传 / make sync-sources\n"
        "· 进度：sync_progress.json → 资料库 / Ops 摄取条",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y_r = banner(draw, right_x, top, rw, "交互面（Turn · 必须快）", ACCENT_SOFT)
    y_r = card(
        draw,
        right_x,
        y_r,
        rw,
        "做什么",
        "· Agent 按需调用 search_sources\n"
        "· embed(query) 一次（毫秒～数十毫秒）\n"
        "· HNSW ∥ 强词OR FTS→Okapi → RRF → 词法重排\n"
        "· two-level doc 加分（默认开）后截断进 tool_result\n"
        "· 旁路写 retrieval.completed 审计（Ops）",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = max(y_l, y_r) + 16
    y = card(
        draw,
        40,
        y,
        W - 80,
        "规模与双库（现行）",
        "· 常设 seed 约 2500 文件量级；产品 source_* 可远大于此（随用户资料涨）。\n"
        "· 嵌入：make resolve-embedding → CPU gte-small@384 / GPU≥8GiB 常为 bge-m3@1024。\n"
        "· Schema A：产品 DATABASE_URL 与 Ops L1（bench-postgres / retrieval_ops）按 Work 分平面；"
        "热路径不 sync。",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    y += 12
    y = footer(
        draw,
        y,
        W,
        ["代码：index_scheduler / sources_watch / tools.search_sources · 文档：docs/15"],
    )
    return save(img, "01-two-planes.png", y)


# ─── 02 chunking ─────────────────────────────────────────────────────────────


def fig_chunking() -> Path:
    W, H = 1400, 1600
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "02 · 切块与嵌入输入（索引面）",
        "chunk_source_text · RQ1a/b/c。目标：一块 ≈ 可引用、可向量化的语义叶；不是任意切 512 token。",
    )

    y = banner(draw, 40, y, W - 80, "从文件到 chunk 行", ACCENT_SOFT)
    steps = [
        ("1. 选文件", "should_index_source\n.md/.txt/.json 等\n跳过 cards/、隐藏文件"),
        ("2. 树切块", "按 #/##/### 成节\n叶优先整节保留\n宽 GFM 表可拆指针"),
        ("3. 长度预算", "软顶默认 4000 字\n重叠默认 400 字\n超长则滑窗"),
        ("4. 拼 embed 文本", "默认仅正文\n(metadata 前缀可关)\nexcerpt 用正文"),
    ]
    gap = 16
    bw = (W - 80 - 3 * gap) // 4
    bottoms = []
    for i, (t, b) in enumerate(steps):
        x = 40 + i * (bw + gap)
        bottoms.append(card(draw, x, y, bw, t, b, fill=ACCENT_SOFT, outline=ACCENT, title_color=ACCENT))
        if i < 3:
            h_arrow(draw, x + bw, y + 55, x + bw + gap)
    y = max(bottoms)
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "写入索引时发生什么", OK_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "批嵌入 → pgvector / JSON store",
        "· embed=False 先切完所有 dirty 文件，再跨文件 batch encode（减少模型调用次数）\n"
        "· SentenceTransformer：normalize_embeddings=True（维数随 profile）\n"
        "· 每行 chunk：chunk_id、path、section_title、text、embedding、visibility/work_id\n"
        "· INDEX_VERSION 变化会强制全量重建；日常靠 mtime 跳过未改文件",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "为何 1 万+ chunk 仍然（intel）", WARN_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "切块粒度 × 语料体量",
        "intel vendor（ATT&CK 技术卡、atomic、actors、hunt 笔记等）单文件常多节 → 一文件多 chunk。\n"
        "约 2500 文件 × 平均数块 ≈ 万级向量行。这是索引面成本，不是查询要扫 1 万篇全文。\n"
        "查询侧：只对 query 嵌一次，再在 HNSW 图上找近邻（见 03）。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y += 12
    y = footer(
        draw,
        y,
        W,
        [
            "参数：retrieval_chunk_max_chars=4000 · overlap=400 · embedding_batch_size=64",
            "代码：retrieval/chunking.py · index_embed.py · pgvector_store.sync",
        ],
    )
    return save(img, "02-chunking-embed.png", y)


# ─── 03 fast hit @10k ────────────────────────────────────────────────────────


def fig_fast_hit() -> Path:
    W, H = 1400, 1700
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "03 · 万级 chunk 如何快速命中",
        "生产默认：pgvector HNSW(cosine) ∥ 强词OR+Okapi → RRF → 词法重排 → doc_boost → top-limit。"
        "复杂度不随「读完全库正文」增长。",
    )

    y = banner(draw, 40, y, W - 80, "查询时刻只做这些（热路径）", ACCENT_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "一次 query 的计算量（默认 limit=30）",
        "1. embed(query) → 1 个单位向量（维数随 profile：384 或 1024）\n"
        "2. 工具多要 fetch_limit=60（有 path_prefix 则 ×3）；店内每车道 top_k≈240\n"
        "3. 向量路：HNSW ANN（vector_cosine_ops）\n"
        "4. 词法路：强词 OR tsquery 召回 → 内存 Okapi 重打分（非 plainto 默认）\n"
        "5. RRF（k=60，1:1）→ L1；词法重排 → L2；CE 默认关\n"
        "6. two-level：约 8 个相关 path 并行算出，重排后 doc_boost 再截断\n"
        "7. 租户 / path_prefix 过滤后工具再截到 limit=30（前 5 条带摘录）",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "HNSW 在干什么（为何不是 O(N) 扫库）", PURPLE_SOFT)
    a = card(
        draw,
        40,
        y,
        640,
        "暴力余弦",
        "对每个 chunk 算 cos(q,c)\n1 万次点积 → 可接受但随 N 线性涨\nJSON/hash 后端小库可用",
        fill=CARD,
    )
    b = card(
        draw,
        720,
        y,
        640,
        "HNSW 近似图检索（生产）",
        "向量预先建成多层近邻图\n查询沿图走，只访一小撮节点\n≈ 对数级探测；详解见 07",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    y = max(a, b)
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "缩小候选：比「全库语义」更省", OK_SOFT)
    cols = [
        ("场景前缀", "intel Profile\ndefault_path_prefix=\nseed/intel\n写作可排除 intel"),
        ("租户 SQL", "seed OR\n当前 work_id\n跨 Work 不可见"),
        ("两级召回", "默认 doc∥chunk\n约 8 path 加分\n超时约 0.3s"),
        ("limit 裁剪", "默认进窗 30 条\n前 5 带摘录\n约 400 字/条"),
    ]
    bw = (W - 80 - 48) // 4
    bottoms = []
    for i, (t, body) in enumerate(cols):
        bottoms.append(
            card(
                draw,
                40 + i * (bw + 16),
                y,
                bw,
                t,
                body,
                fill=OK_SOFT,
                outline=OK,
                title_color=OK,
            )
        )
    y = max(bottoms) + 12
    y = card(
        draw,
        40,
        y,
        W - 80,
        "和「索引未完成」的关系",
        "HNSW 只覆盖已经写入的行。旁路嵌库进行中时，只能命中已投影部分（可能 index_lag）。"
        "IOC 卡 enrich/lookup 不依赖向量，可先用。完整语义检索要等摄取追上。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y += 12
    y = footer(
        draw,
        y,
        W,
        [
            "索引：CREATE INDEX … USING hnsw (embedding vector_cosine_ops)",
            "代码：pgvector_store.search_hybrid · fusion.reciprocal_rank_fusion · scenario_scope",
        ],
    )
    return save(img, "03-fast-hit-ann.png", y)


# ─── 04 search_sources ───────────────────────────────────────────────────────


def fig_search_sources() -> Path:
    W, H = 1400, 2100
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "04 · search_sources 端到端",
        "工具入口到 tool_result。默认 hybrid；limit=30；强词 OR + 等权 RRF（产品冻结线）。",
    )

    flow = [
        (
            ACCENT_SOFT,
            ACCENT,
            "① 入口",
            "解析 scenario 默认/排除前缀；begin_audit_capture() 打开 L1/L2 捕获槽。"
            "对外 limit=30；对内 fetch_limit=60（有 path_prefix 则 90）。",
        ),
        (
            WARN_SOFT,
            WARN,
            "② 模式分支",
            "keyword：扫盘词法。hybrid/vector：store.search（永不 sync）。"
            "空/cover 未盖住 → keyword-fallback；keyword 仍空可保留 ANN（不整单抹空）。",
        ),
        (
            PURPLE_SOFT,
            PURPLE,
            "③ 店内召回（chunk 车道 ∥ doc 车道）",
            "向量 HNSW ≤240 ∥ 词法（强词 OR FTS → Okapi）≤240 → RRF(k=60,1:1)→L1 → "
            "词法重排→L2。并行约 8 个相关 path；重排之后 doc_boost(0.35) merge，交回 ≤60。",
        ),
        (
            OK_SOFT,
            OK,
            "④ 回工具层 → L3",
            "租户过滤 → path_prefix/exclude → 截成 ≤30 → 分层呈现（前 5 条约 400 字摘录，"
            "其余多 path/标题/分）→ entered_context（L3）。",
        ),
        (
            ACCENT_SOFT,
            ACCENT,
            "⑤ 返回与旁路事件",
            "hits + retrieval 元数据给 Agent；retrieval.completed.payload.audit 供 Ops 只读，不进模型窗。",
        ),
    ]
    for fill, outline, t, body in flow:
        y = card(draw, 40, y, W - 80, t, body, fill=fill, outline=outline, title_color=outline)
        if t.startswith("⑤"):
            break
        y = v_arrow(draw, W // 2, y)

    y += 8
    y = footer(
        draw,
        y,
        W,
        ["代码：tools.search_sources · retrieval/audit.py · docs/15 A9"],
    )
    return save(img, "04-search-sources.png", y)


# ─── 05 similarity ───────────────────────────────────────────────────────────


def fig_similarity() -> Path:
    W, H = 1400, 1750
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "05 · 相似度：归一化、点积、欧氏、余弦",
        "向量通道内部怎么比「像不像」。本项目默认按余弦语义；入库已单位化后实现可用点积。",
    )

    y = banner(draw, 40, y, W - 80, "四个量", ACCENT_SOFT)
    items = [
        ("长度 ‖v‖", "√Σvᵢ²\n箭有多长"),
        ("归一化", "v/‖v‖\n长度收成 1\n方向不变"),
        ("点积", "Σ qᵢcᵢ\n越大越同向\n吃长度"),
        ("欧氏", "‖q−c‖\n越小越近\n吃长度"),
    ]
    bw = (W - 80 - 48) // 4
    bottoms = []
    for i, (t, b) in enumerate(items):
        bottoms.append(card(draw, 40 + i * (bw + 16), y, bw, t, b))
    y = max(bottoms) + 10
    y = card(
        draw,
        40,
        y,
        W - 80,
        "余弦 = 点积 / (‖q‖‖c‖)",
        "除掉两边长度，只留夹角。越接近 +1 越相关。这是「意思方向像不像」的度量。",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "长度如何干扰欧氏 / 裸点积", WARN_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "同主题、不同模长",
        "Q=(1,0)。甲≈(0.9,0.1)，乙同向但被扩写拉长≈(8,1)。\n"
        "余弦：两者都 ≈0.99（都对）。裸点积：乙虚高。欧氏：乙「远」很多 → 长文档可能掉出前列。\n"
        "所以说：欧氏仍受长度影响；RAG 要比方向时，余弦（或先归一化再比）更稳。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "本项目做法", OK_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "先单位化，再按余弦近邻理解",
        "· ST encode：normalize_embeddings=True；HashEmbedder 手写 L2 归一化\n"
        "· pgvector：vector_cosine_ops + HNSW；JSON 路径用 cosine_similarity\n"
        "· 两边都已单位化时：点积 ≡ 余弦，名次与单位球上的欧氏序一致\n"
        "· 与 BM25 分数尺度不同 → 必须用 RRF 融名次，不能直接加分",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y += 12
    y = footer(
        draw,
        y,
        W,
        ["代码：embedder.py · pgvector_store（hnsw / vector_cosine_ops）· docs/15 §3.4"],
    )
    return save(img, "05-similarity-metrics.png", y)


# ─── 06 ops L1 L2 L3 ─────────────────────────────────────────────────────────


def fig_ops_audit() -> Path:
    W, H = 1400, 1550
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "06 · Ops 检索审计：L1 → L2 → L3",
        "/ops/<secret>/retrieval 只读真实用户 Turn 的旁路快照。评测台 /test 是另一条线。",
    )

    a = card(
        draw,
        40,
        y,
        640,
        "评测台 /test",
        "golden / ci-proof\n人造用例 + scratch\n验契约与轨迹",
    )
    b = card(
        draw,
        720,
        y,
        640,
        "检索审计 /retrieval（本图）",
        "真实前台 Turn\n展示三层 audit\n不写 workspace、不代重搜",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = max(a, b)
    y = v_arrow(draw, W // 2, y)

    y = card(
        draw,
        40,
        y,
        W - 80,
        "数据从哪来",
        "search_sources 内 begin_audit_capture → 店内写入 recall_pool / ranked → "
        "结束时合成 entered_context，挂到 retrieval.completed.payload.audit。",
        fill=CARD,
    )
    y = v_arrow(draw, W // 2, y)

    layers = [
        (
            PURPLE_SOFT,
            PURPLE,
            "L1 recall_pool · 召回池",
            "重排前捞到的候选（常 fused）。偏宽（审计上限约 20）。回答：系统先看见谁。",
        ),
        (
            WARN_SOFT,
            WARN,
            "L2 ranked · 排序结果",
            "chunk 车道内词法重排后的顺序（CE 默认关）。"
            "two-level doc_boost 发生在 L2 之后、交工具截断之前。"
            "若 hybrid 且三层完全同构，多半是捕获兜底，不是「三层本该一样」。",
        ),
        (
            OK_SOFT,
            OK,
            "L3 entered_context · 进窗摘录",
            "真正写入 tool_result、模型下一步能读到的短摘录。"
            "含 truncated/char_len。默认条数 = limit（常 30；前 5 带摘录）。",
        ),
    ]
    for i, (fill, outline, t, body) in enumerate(layers):
        y = card(draw, 40, y, W - 80, t, body, fill=fill, outline=outline, title_color=outline)
        if i < len(layers) - 1:
            y = v_arrow(draw, W // 2, y, gap=22)

    y += 8
    y = card(
        draw,
        40,
        y,
        W - 80,
        "页面上怎么用",
        "浏览最近有检索的 Turn → 点开看三层与层差高亮 → 诊断条提示无 audit/全截断等 → 可导出 JSON。"
        "健康形态常见：L1 条数 ≥ L2 ≥ L3。",
        fill=CARD,
    )
    y += 12
    y = footer(
        draw,
        y,
        W,
        ["代码：retrieval/audit.py · Ops RetrievalAuditPage · docs/29 §6"],
    )
    return save(img, "06-ops-audit-l1-l2-l3.png", y)


# ─── 07 HNSW principle (data-flow / algorithm) ───────────────────────────────


def fig_hnsw() -> Path:
    """Build + search data flow — not just multilayer shape."""
    W, H = 1480, 3200
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "07 · HNSW 原理与数据流转",
        "重点：插入时图怎么长出来、查询时状态怎么变。形态见下文；算法对齐 Malkov & Yashunin。"
        "本仓：pgvector hnsw + vector_cosine_ops，查询 embedding <=> q。",
    )

    # —— 0 输入输出 ——
    y = banner(draw, 40, y, W - 80, "〇 先钉死：进出各是什么数据", ACCENT_SOFT)
    a = card(
        draw,
        40,
        y,
        680,
        "建图输入（索引面）",
        "每个 chunk 一条：向量 v∈R^384（已单位化）\n"
        "+ 行身份（chunk_id / path…）\n"
        "本仓：sync 批嵌入后 INSERT source_chunks\n"
        "→ pgvector 为每一行维护 HNSW 结点与边",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    b = card(
        draw,
        760,
        y,
        680,
        "查询输入 / 输出（交互面）",
        "入：q = embed(query)（同样 384、单位化）\n"
        "出：按余弦距离最近的 k 行（再交给 hybrid/RRF）\n"
        "SQL：ORDER BY embedding <=> q LIMIT k\n"
        "距离越小越近；score 常取 1−距离",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = max(a, b)
    y = v_arrow(draw, W // 2, y)

    # —— 1 图上存什么 ——
    y = banner(draw, 40, y, W - 80, "① 图上到底存了什么（状态）", PURPLE_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "不是「文件夹」，是带层号的邻接表",
        "对每个结点 u：\n"
        "· 向量 u.vec\n"
        "· 最高层号 u.level（随机抽，多数=0，少数到上层）\n"
        "· 每一层一张邻居表 Neighbors[u][ℓ]（无向边，度数 ≤ M / Mmax）\n"
        "全局：入口点 enter_point（通常是当前最高层上的某个点）\n"
        "距离函数 dist(a,b)：本仓为余弦距离（cosine_ops 下的 <=>）",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    y = v_arrow(draw, W // 2, y)

    # —— 2 insert data flow ——
    y = banner(draw, 40, y, W - 80, "② 插入一条向量：数据怎么流（建图核心）", OK_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "步骤 A — 抽层号",
        "新点 v 到来 → 按几何分布随机抽 level=L（P(升一层)≈1/m_L，上层越来越稀）。\n"
        "L 决定：v 会出现在层 0…L；更高层根本没有这个点。",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y = v_arrow(draw, W // 2, y, gap=20)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "步骤 B — 从上往下「落到」层 L+1（只走路，不连边）",
        "ep ← 当前 enter_point\n"
        "对 ℓ = top_layer … L+1：\n"
        "  在层 ℓ 做贪心 SEARCH（ef=1）：只保留离 v 最近的 1 个点，更新 ep\n"
        "含义：用高速公路把 ep 挪到「离新点较近」的区域，还不占用 v 的邻居名额。",
        fill=CARD,
    )
    y = v_arrow(draw, W // 2, y, gap=20)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "步骤 C — 在层 L…0：搜候选 → 选邻居 → 写边（数据真正改图）",
        "对 ℓ = L … 0：\n"
        "  1) W ← SEARCH-LAYER(目标=v, 入口=ep, ef=efConstruction, 层=ℓ)\n"
        "     · 维护候选小根堆 C、结果集 W、已访问集合 visited\n"
        "     · 反复：取出 C 中离 v 最近的 c；若 c 已比 W 里最远的还远 → 停\n"
        "     · 否则扫 Neighbors[c][ℓ] 里未访问点，算 dist(v,·)，推进 C/W\n"
        "  2) N ← SELECT-NEIGHBORS(v, W, M)  （从 W 里挑最多 M 个近邻；可用启发式保连通）\n"
        "  3) 写边：对每个 n∈N，双向加入 Neighbors[v][ℓ]↔Neighbors[n][ℓ]\n"
        "  4) 若某邻居度数 > Mmax：删掉它「最远」的一条边（剪枝，防度数爆炸）\n"
        "  5) ep ← W 中最接近 v 的点，作为下一层入口\n"
        "层 0 同样做完后，v 已挂进底层密图。",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y = v_arrow(draw, W // 2, y, gap=20)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "步骤 D — 更新入口",
        "若 L > 原 top_layer：enter_point ← v，top_layer ← L。\n"
        "下一条 INSERT 重复 A→D。本仓万级 chunk = 对 HNSW 引擎连续插入万次（批写入时由 pgvector 完成）。",
        fill=CARD,
    )
    y = v_arrow(draw, W // 2, y)

    # —— 3 SEARCH-LAYER detail ——
    y = banner(draw, 40, y, W - 80, "③ 子过程 SEARCH-LAYER：一次层内扩展的数据流", WARN_SOFT)
    cols = [
        ("状态", "visited 集合\n候选堆 C（近优先）\n结果堆 W（远优先/有界）"),
        ("循环", "弹出 C 最近点 c\n若比 W 最远还远→停\n否则展开邻居"),
        ("扩展", "对邻居 e∉visited\n算 dist(目标,e)\n更新 C 与 W"),
        ("产出", "W = 本层找到的\n最多 ef 个近邻\n交给上层算法"),
    ]
    bw = (W - 80 - 48) // 4
    bottoms = []
    for i, (t, body) in enumerate(cols):
        bottoms.append(
            card(
                draw,
                40 + i * (bw + 16),
                y,
                bw,
                t,
                body,
                fill=WARN_SOFT,
                outline=WARN,
                title_color=WARN,
            )
        )
    y = max(bottoms)
    y = v_arrow(draw, W // 2, y)

    # —— 4 query ——
    y = banner(draw, 40, y, W - 80, "④ 查询一条 q：数据怎么流（热路径）", ACCENT_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "上层贪心下沉（ef=1）→ 底层宽搜（efSearch）→ top-k",
        "ep ← enter_point\n"
        "对 ℓ = top_layer … 1：\n"
        "  ep ← SEARCH-LAYER(q, ep, ef=1, ℓ) 里离 q 最近的那一个\n"
        "     （每层只跟「当前最近」走，快速缩小区域）\n"
        "层 0：\n"
        "  W ← SEARCH-LAYER(q, ep, ef=efSearch, 0)\n"
        "     （efSearch 更大 → 多看几个候选，召回更好、稍慢）\n"
        "返回 W 中距离最小的 k 个结点 → 映射回 source_chunks 行。\n"
        "本仓 hybrid：这 k（或 top_k）再与 BM25 路做 RRF，不是只信 HNSW。",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = v_arrow(draw, W // 2, y)

    # —— 5 why approximate + params ——
    y = banner(draw, 40, y, W - 80, "⑤ 关键参数如何改变数据流（直觉）", PURPLE_SOFT)
    a = card(
        draw,
        40,
        y,
        680,
        "建图侧",
        "M / Mmax：每个点每层最多连几条边\n"
        "越大图越密、越占内存、插入越慢、查询召回常更好\n"
        "efConstruction：插入时 SEARCH 的 W 宽度\n"
        "越大建图越慢、边质量通常更好",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    b = card(
        draw,
        760,
        y,
        680,
        "查询侧",
        "efSearch：底层 W 宽度\n"
        "越大越接近精确近邻、延迟↑\n"
        "k / LIMIT：最终只要前 k\n"
        "本仓常先取 limit×4 再过滤/融合",
        fill=CARD,
    )
    y = max(a, b)
    y = v_arrow(draw, W // 2, y)

    y = banner(draw, 40, y, W - 80, "⑥ 和本仓路径对齐（谁触发上述流转）", OK_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "sync → INSERT 行 → 引擎跑「②插入」；search_vector → 引擎跑「④查询」",
        "· ensure_schema：CREATE INDEX … USING hnsw (embedding vector_cosine_ops)\n"
        "· 旁路 sync：chunk→embed→写入 embedding 列；索引维护 = 连续插入/更新图\n"
        "· search_vector：embed(query) 后 ORDER BY embedding <=> q LIMIT k\n"
        "· 不在应用代码里手写邻居表；数据流转发生在 pgvector/HNSW 实现内部\n"
        "· 应用层只保证：单位化向量 + cosine_ops + hybrid 补召回",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y += 10
    y = footer(
        draw,
        y,
        W,
        [
            "图 03=为何要用 ANN；图 08=抽层；图 09=查询同门不同命中；本图=插入/层内扩展/查询总览。",
            "代码落点：pgvector_store.ensure_schema / search_vector · 论文：Malkov & Yashunin, HNSW 2016",
        ],
    )
    return save(img, "07-hnsw-principle.png", y)


def fig_hnsw_layer_sample() -> Path:
    """Layer-id sampling formula: pipeline + probs + density sketch."""
    W, H = 1400, 2100
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "08 · HNSW 层号怎么抽（为何大多 L=0）",
        "插入新点时与距离无关：掷一次 U，再套公式得到最高层号 L。"
        "本仓默认 M=16 → mL≈0.3607。细节见 RAG-mental-model §5.0b · 2.2 A。",
    )

    # —— 公式总览 ——
    y = banner(draw, 40, y, W - 80, "① 一次插入 = 掷骰子走这条流水线", ACCENT_SOFT)

    steps = [
        ("U", "Uniform(0,1)\n均匀随机\n与向量无关", ACCENT_SOFT, ACCENT),
        ("−ln(U)", "翻成正数\n→ 指数分布\n多数偏小", WARN_SOFT, WARN),
        ("× mL", "mL = 1/ln(M)\nM=16 时\nmL≈0.3607", PURPLE_SOFT, PURPLE),
        ("floor", "向下取整\n得到整数\nL = 0,1,2…", OK_SOFT, OK),
    ]
    box_w, box_h, gap = 240, 118, 28
    total = len(steps) * box_w + (len(steps) - 1) * gap
    x0 = (W - total) // 2
    by = y
    for i, (title, body, fill, outline) in enumerate(steps):
        x = x0 + i * (box_w + gap)
        draw.rounded_rectangle(
            (x, by, x + box_w, by + box_h), radius=10, fill=fill, outline=outline, width=2
        )
        draw.text((x + 14, by + 10), title, fill=outline, font=font(20, bold=True))
        ty = by + 42
        for line in body.split("\n"):
            draw.text((x + 14, ty), line, fill=MUTED, font=font(13))
            ty += 20
        if i < len(steps) - 1:
            h_arrow(draw, x + box_w + 2, by + box_h // 2, x + box_w + gap - 2)
    y = by + box_h + 16

    draw.rounded_rectangle(
        (40, y, W - 40, y + 52), radius=10, fill=CARD, outline=BORDER, width=2
    )
    formula = "L = floor( −ln(U) · mL )     其中 mL = 1 / ln(M)"
    fw = tw(draw, formula, font(18, bold=True))
    draw.text(((W - fw) // 2, y + 14), formula, fill=INK, font=font(18, bold=True))
    y += 68
    y = v_arrow(draw, W // 2, y, gap=20)

    # —— 概率：为何大多 0 ——
    y = banner(draw, 40, y, W - 80, "② 概率不是「每层一样」——按 M^(−ℓ) 指数变稀", WARN_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "关键结论（M=16）",
        "P(L ≥ ℓ) = M^(−ℓ) = 16^(−ℓ)\n"
        "→ P(L=0)≈93.75%（只在底层）　P(L=1)≈5.86%　P(L=2)≈0.37%　更高更稀\n"
        "「随机」= 指数衰减随机；高层必须稀，才能当远跳高速路。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y += 12

    # horizontal bar chart
    bars = [
        ("L = 0", 0.9375, "≈93.75%  只出现在层 0", OK),
        ("L = 1", 0.0586, "≈5.86%   层 0+1", ACCENT),
        ("L = 2", 0.0037, "≈0.37%   层 0+1+2", PURPLE),
        ("L ≥ 3", 0.00024, "≈0.024%  极少", DANGER),
    ]
    label_w, bar_max, row_h = 90, 780, 44
    bx = 40 + label_w + 20
    max_frac = bars[0][1]
    for label, frac, note, color in bars:
        # L=0 拉满；更小概率保底可见一截
        bw = max(22, int(bar_max * (frac / max_frac)))
        draw.text((40, y + 10), label, fill=INK, font=font(15, bold=True))
        draw.rounded_rectangle(
            (bx, y + 6, bx + bw, y + 34), radius=6, fill=color, outline=color
        )
        draw.text((bx + bw + 12, y + 10), note, fill=MUTED, font=font(14))
        y += row_h
    y += 8
    y = v_arrow(draw, W // 2, y, gap=20)

    # —— 层密度示意 ——
    y = banner(draw, 40, y, W - 80, "③ 图上看：底层密、上层稀（同一批点的户籍）", PURPLE_SOFT)
    layer_y0 = y
    layers = [
        (2, 3, "层 2 · 极稀 · 远跳", PURPLE),
        (1, 8, "层 1 · 较少", ACCENT),
        (0, 28, "层 0 · 几乎全员（密图）", OK),
    ]
    max_n = 28
    lane_h = 70
    for i, (lev, n, caption, color) in enumerate(layers):
        ly = layer_y0 + i * (lane_h + 14)
        draw.rounded_rectangle(
            (40, ly, W - 40, ly + lane_h),
            radius=10,
            fill=CARD,
            outline=BORDER,
            width=2,
        )
        draw.text((56, ly + 12), caption, fill=color, font=font(15, medium=True))
        # dots centered
        r = 7
        span = min(W - 200, n * 28)
        sx = (W - span) // 2
        cy = ly + 44
        for j in range(n):
            cx = sx + int(j * span / max(n - 1, 1)) if n > 1 else W // 2
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color, outline=color)
        # fade note for L=0
        if lev == 0:
            draw.text(
                (W - 220, ly + 12),
                f"示意 {n}/{max_n}+ …",
                fill=MUTED,
                font=font(12),
            )
    y = layer_y0 + len(layers) * (lane_h + 14) + 4
    y = card(
        draw,
        40,
        y,
        W - 80,
        "读图",
        "抽到 L=k 的点会出现在层 0…k（上层点一定也在下层）。"
        "查询从稀的高层入口下沉到密的层 0 精修。",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    y = v_arrow(draw, W // 2, y, gap=20)

    # —— 手算 ——
    y = banner(draw, 40, y, W - 80, "④ 手算两例（M=16, mL≈0.3607）", OK_SOFT)
    a = card(
        draw,
        40,
        y,
        660,
        "例 1 · U=0.5 → L=0",
        "−ln(0.5) ≈ 0.693\n"
        "0.693 × 0.3607 ≈ 0.250\n"
        "floor(0.250) = 0\n"
        "→ 只在层 0 建边（常见）",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    b = card(
        draw,
        720,
        y,
        640,
        "例 2 · U=0.02 → L=1",
        "−ln(0.02) ≈ 3.912\n"
        "3.912 × 0.3607 ≈ 1.411\n"
        "floor(1.411) = 1\n"
        "→ 在层 1 与层 0 都建边",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = max(a, b) + 16

    y = footer(
        draw,
        y,
        W,
        [
            "与距离无关：层号不看 cosine；距离只用于同层选邻居 / 查询走路。",
            "对照：图 07 插入步骤 A；文字公式推导：docs/RAG-mental-model.md §5.0b · 2.2 A",
        ],
    )
    return save(img, "08-hnsw-layer-sample.png", y)


def fig_hnsw_query_walk() -> Path:
    """Query-time walk: enter_point + dist as ruler, not address."""
    W, H = 1480, 2400
    img, draw = new_img(W, H)
    y = title_block(
        draw,
        W,
        "09 · 查询怎么沿图走到命中 chunk",
        "search_sources 向量路：q 不分层、不进图；每次都从同一 enter_point 进门；"
        "dist 只用来在邻居里比谁更近——不是把某个小数映射成「某一簇」。"
        "这正是 RAG 热路径上「不同问句命中不同块」的机制。",
    )

    # —— 0 先钉死误解 ——
    y = banner(draw, 40, y, W - 80, "〇 先钉死三件事（常见误解）", DANGER_SOFT)
    a = card(
        draw,
        40,
        y,
        450,
        "① q 不抽层",
        "随机 L 只在插入 chunk 时发生。\n"
        "query → embed → q，只当靶子，\n"
        "没有自己的层号，也不写入图。",
        fill=DANGER_SOFT,
        outline=DANGER,
        title_color=DANGER,
    )
    b = card(
        draw,
        510,
        y,
        450,
        "② 门总是同一扇",
        "每次查询通常从全局 enter_point\n"
        "出发（建图时维护好的大门）。\n"
        "区分结果不靠换门，靠换 q。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    c = card(
        draw,
        980,
        y,
        460,
        "③ dist 不是地址",
        "算出 0.3 不会「对应某簇」。\n"
        "它只在候选之间比大小：\n"
        "谁离 q 更近，就往谁走。",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = max(a, b, c) + 8
    y = v_arrow(draw, W // 2, y, gap=20)

    # —— 1 尺子 ——
    y = banner(draw, 40, y, W - 80, "① 每一步在算什么（本仓余弦距离）", ACCENT_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "尺子：dist(q, 老点) = 1 − (q·老点)",
        "老点 = 早已入库的 chunk 向量（图上结点），不是「以前命中过的」。\n"
        "cos = q·老点（约 −1～1，越像越大）；走路比的是 dist（约 0～2，越小越近）。\n"
        "边决定「旁边有谁」；dist 决定「对当前这个 q，邻居里选谁」。",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = v_arrow(draw, W // 2, y, gap=20)

    # —— 2 一步算法 ——
    y = banner(draw, 40, y, W - 80, "② 一层里的一步：只看当前点的邻居（不扫全层）", OK_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "贪心挪步（伪代码心智）",
        "P ← enter_point（或上层传下来的入口）\n"
        "反复：\n"
        "  取出 P 在本层的邻居 N1,N2,…（度数 ≤ M，不是该层全部点）\n"
        "  分别算 dist(q,P), dist(q,N1), dist(q,N2), …\n"
        "  若某个 Ni 比 P 离 q 更近 → P ← Ni，继续\n"
        "  否则本层停（底层会用更大 ef_search 多留几个候选）\n"
        "然后层号减一，带着 P 下沉；到层 0 取出距离最小的 k 个 → 命中的 chunk。",
        fill=OK_SOFT,
        outline=OK,
        title_color=OK,
    )
    y = v_arrow(draw, W // 2, y, gap=20)

    # —— 3 同门不同路 ——
    y = banner(draw, 40, y, W - 80, "③ 同一扇门 + 不同 q → 不同路径 → 不同 chunk", PURPLE_SOFT)

    # ASCII-ish graph cards
    left = card(
        draw,
        40,
        y,
        680,
        "Query A → qA",
        "图（示意）：enter — A — B\n"
        "                  \\— C\n"
        "\n"
        "算得：dist(qA,A)=0.40\n"
        "      dist(qA,B)=0.20  ← 更近\n"
        "      dist(qA,C)=0.50\n"
        "从 A 走向 B → 命中靠近 B 的一批 chunk",
        fill=PURPLE_SOFT,
        outline=PURPLE,
        title_color=PURPLE,
    )
    right = card(
        draw,
        760,
        y,
        680,
        "Query B → qB（同一张图、同一 enter）",
        "图（示意）：enter — A — B\n"
        "                  \\— C\n"
        "\n"
        "算得：dist(qB,A)=0.40\n"
        "      dist(qB,B)=0.60\n"
        "      dist(qB,C)=0.15  ← 更近\n"
        "从 A 走向 C → 命中靠近 C 的另一批 chunk",
        fill=ACCENT_SOFT,
        outline=ACCENT,
        title_color=ACCENT,
    )
    y = max(left, right) + 10
    y = card(
        draw,
        40,
        y,
        W - 80,
        "为何会「命中不同 chunk」？",
        "不是 dist 的某个取值映射到固定簇 ID；\n"
        "而是不同 q 让「邻居远近排序」变了 → 下一步走的边变了 → 最终停在向量空间不同邻域。\n"
        "算法无显式簇标签；「簇」只是对邻域的口语直觉。",
        fill=CARD,
        outline=BORDER,
    )
    y = v_arrow(draw, W // 2, y, gap=20)

    # —— 4 RAG 对齐 ——
    y = banner(draw, 40, y, W - 80, "④ 接到本仓 RAG 热路径", WARN_SOFT)
    y = card(
        draw,
        40,
        y,
        W - 80,
        "search_sources（向量支路）",
        "用户/模型写出 query 字符串\n"
        "  → embed → q（单位化；维数随 embedding profile）\n"
        "  → pgvector HNSW：从上图「②③」走出 top-k 行（ORDER BY embedding <=> q）\n"
        "  → 与词法路（强词OR→Okapi）RRF → 重排 → doc_boost → 截断摘录进窗\n"
        "索引面早已建好图；热路径只走路，不抽 L、不改边。",
        fill=WARN_SOFT,
        outline=WARN,
        title_color=WARN,
    )
    y += 12

    y = footer(
        draw,
        y,
        W,
        [
            "对照：图 07=建图+查询总览；图 08=插入时抽 L；本图=查询时为何同门不同命中。",
            "文字：docs/RAG-mental-model.md §5.0b · 4（查询走路详解）",
        ],
    )
    return save(img, "09-hnsw-query-walk.png", y)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Remove previous assets in this folder
    for old in OUT.glob("*.png"):
        old.unlink()
        print("deleted", old.name)

    paths = [
        fig_two_planes(),
        fig_chunking(),
        fig_fast_hit(),
        fig_search_sources(),
        fig_similarity(),
        fig_ops_audit(),
        fig_hnsw(),
        fig_hnsw_layer_sample(),
        fig_hnsw_query_walk(),
    ]
    for p in paths:
        im = Image.open(p)
        print(f"wrote {p.name}  {im.size[0]}x{im.size[1]}")


if __name__ == "__main__":
    main()
