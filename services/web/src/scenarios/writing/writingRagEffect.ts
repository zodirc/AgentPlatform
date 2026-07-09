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

const SOURCE_INTENT_RE =
  /引用|参考|出处|资料|sources?|cite|根据.{0,8}资料|based on/i;

export function userNeedsSources(userMessage: string | null | undefined): boolean {
  if (!userMessage?.trim()) return false;
  return SOURCE_INTENT_RE.test(userMessage);
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
  const retrievals = (view?.artifacts ?? []).filter((a) => a.type === "retrieval");
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
      detail: needsSources
        ? "等待模型检索 sources/ 资料…"
        : "本轮进行中",
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
        "需要引用资料时，说明「根据 sources 写一段并标注引用」；自由改稿无需检索。",
      searched: false,
      hitCount: 0,
      cites: [],
    };
  }

  if (!needsSources && !searched && cites.length === 0) {
    return {
      status: "not_needed",
      title: "本轮未用资料检索",
      detail: "改稿/自由写作通常不需要 search_sources；若要引用 sources/ 请明确说明。",
      searched: false,
      hitCount: 0,
      cites: [],
    };
  }

  if (needsSources && !searched) {
    return {
      status: "no_search",
      title: "未检索资料",
      detail:
        "你已要求引用/资料，但模型未调用 search_sources。可重试并写明「先 search_sources 再写」。",
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
      detail: `已找到 ${hitCount} 条资料，但输出中尚无 [cite:xxx]。RAG 对本轮成稿尚未生效。`,
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
    title: "本轮未用资料检索",
    detail: "未检测到资料引用需求或检索活动。",
    searched,
    hitCount,
    cites,
  };
}
