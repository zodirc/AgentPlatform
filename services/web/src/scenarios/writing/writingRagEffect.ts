import type { TurnView } from "../../shared/api/client";

export type RagEffectStatus =
  | "idle"
  | "running"
  | "not_needed"
  | "no_search"
  | "no_hits"
  | "no_cite"
  | "effective";

export type RagEffectAssessment = {
  status: RagEffectStatus;
  title: string;
  detail: string;
  searched: boolean;
  hitCount: number;
  cites: string[];
};

const CITE_RE = /\[cite:[\w-]+\]/g;

/** Evidence-backed drafting — not bare mentions of「资料」/ library meta-questions. */
const SOURCE_DRAFT_INTENT_RE =
  /根据.{0,16}(资料|sources)|(?:写|起草|成稿|扩写).{0,12}(引用|出处)|标注引用|引用资料|参考资料写|用\s*sources|from sources|based on (the )?sources?|\bcite\b/i;

/** Questions about the library itself — browsing is fine; do not demand search_sources. */
const LIBRARY_META_RE =
  /资料库.{0,12}(理解|有什么|是什么|介绍|看看|内容)|对.{0,8}资料库|(?:sources\/?|资料库).{0,8}(目录|列表|有哪些)|有哪些资料/i;

export function userNeedsSources(
  userMessage: string | null | undefined,
): boolean {
  if (!userMessage?.trim()) return false;
  if (LIBRARY_META_RE.test(userMessage)) return false;
  return SOURCE_DRAFT_INTENT_RE.test(userMessage);
}

function collectOutputText(
  view: TurnView | null,
  streamText: string,
  sectionDraft: string,
): string {
  const chunks: string[] = [];
  if (streamText) chunks.push(streamText);
  if (sectionDraft) chunks.push(sectionDraft);
  if (view?.latest_output) chunks.push(view.latest_output);
  for (const art of view?.artifacts ?? []) {
    if (typeof art.content === "string") chunks.push(art.content);
    if (typeof art.new_text === "string") chunks.push(art.new_text);
  }
  return chunks.join("\n");
}

export function extractCites(text: string): string[] {
  const found = text.match(CITE_RE) ?? [];
  return [...new Set(found)];
}

export function assessWritingRagEffect(options: {
  view: TurnView | null;
  streamText: string;
  sectionDraft: string;
  userMessage: string | null | undefined;
  turnBusy: boolean;
}): RagEffectAssessment {
  const { view, streamText, sectionDraft, userMessage, turnBusy } = options;
  const needsSources = userNeedsSources(userMessage);
  const retrievals = (view?.artifacts ?? []).filter(
    (a) => a.type === "retrieval",
  );
  const searched =
    retrievals.length > 0 ||
    (view?.tool_timeline ?? []).some((t) => t.tool_name === "search_sources");
  const hitCount = retrievals.reduce(
    (sum, r) => sum + (typeof r.hit_count === "number" ? r.hit_count : 0),
    0,
  );
  const outputText = collectOutputText(view, streamText, sectionDraft);
  const cites = extractCites(outputText);

  if (turnBusy && !searched) {
    return {
      status: "running",
      title: "处理中",
      detail: needsSources ? "等待模型检索 sources/…" : "本轮进行中",
      searched: false,
      hitCount: 0,
      cites: [],
    };
  }

  if (!view && !streamText && !sectionDraft) {
    return {
      status: "idle",
      title: "资料引用",
      detail:
        "search_sources 始终可用；成稿需要证据时模型应自行检索并标注 [cite:…]。本面板只观察本轮是否走了检索→引用链路。",
      searched: false,
      hitCount: 0,
      cites: [],
    };
  }

  if (!needsSources && !searched && cites.length === 0) {
    return {
      status: "not_needed",
      title: "本轮未走检索引用",
      detail:
        "未判定为「依资料成稿」意图（例如只是了解资料库、改稿、自由写）。浏览 sources/ 可用 list_dir/read_file，不必强求 search_sources。",
      searched: false,
      hitCount: 0,
      cites: [],
    };
  }

  if (needsSources && !searched) {
    return {
      status: "no_search",
      title: "成稿意图未检索",
      detail:
        "本轮像是要依 sources 成稿/引用，但未调用 search_sources。可重试；无需背诵固定口令，说清要写什么、依据哪类资料即可。",
      searched: false,
      hitCount: 0,
      cites: [],
    };
  }

  if (searched && hitCount === 0) {
    return {
      status: "no_hits",
      title: "检索无命中",
      detail: "search_sources 已执行，但 sources/ 中无匹配内容；无法引用证据。",
      searched: true,
      hitCount: 0,
      cites: [],
    };
  }

  if (searched && hitCount > 0 && cites.length === 0) {
    return {
      status: "no_cite",
      title: "检索命中，成稿未引用",
      detail: `已找到 ${hitCount} 条资料，但输出中尚无 [cite:xxx]。RAG 对本轮成稿尚未闭环。`,
      searched: true,
      hitCount,
      cites: [],
    };
  }

  if (searched && hitCount > 0 && cites.length > 0) {
    return {
      status: "effective",
      title: "资料引用已生效",
      detail: `检索 ${hitCount} 条命中，成稿含 ${cites.join(" ")}。`,
      searched: true,
      hitCount,
      cites,
    };
  }

  if (cites.length > 0) {
    return {
      status: "effective",
      title: "成稿含引用标记",
      detail: cites.join(" "),
      searched,
      hitCount,
      cites,
    };
  }

  return {
    status: "not_needed",
    title: "本轮未走检索引用",
    detail: "未检测到依资料成稿意图，也未发生 search_sources。",
    searched,
    hitCount,
    cites,
  };
}
