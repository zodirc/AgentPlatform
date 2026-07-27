/** Parse OpenAI/Anthropic-ish message payloads for Ops timeline UI. */

export type ContentSegment =
  | { kind: "text"; text: string }
  | { kind: "tool_call"; name: string; detail: string }
  | { kind: "tool_result"; text: string; toolUseId?: string }
  | { kind: "other"; text: string };

export type TimelineRow = {
  index: number;
  role: string;
  kind: "system" | "user" | "assistant" | "tool" | "other";
  title: string;
  toolNames: string[];
  isRuntimeContext: boolean;
  segments: ContentSegment[];
};

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function contentBlocks(content: unknown): unknown[] {
  if (typeof content === "string") return [{ type: "text", text: content }];
  if (Array.isArray(content)) return content;
  if (content == null) return [];
  return [content];
}

function prettyJson(value: unknown): string {
  try {
    if (typeof value === "string") {
      try {
        return JSON.stringify(JSON.parse(value), null, 2);
      } catch {
        return value;
      }
    }
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function parseSegments(blocks: unknown[]): ContentSegment[] {
  const out: ContentSegment[] = [];
  for (const block of blocks) {
    if (typeof block === "string") {
      if (block) out.push({ kind: "text", text: block });
      continue;
    }
    const o = asRecord(block);
    if (!o) {
      out.push({ kind: "other", text: prettyJson(block) });
      continue;
    }
    const type = String(o.type || "");

    if (type === "tool_result" || (o.tool_use_id && !o.name && type !== "text")) {
      const raw =
        typeof o.content === "string"
          ? o.content
          : o.content != null
            ? prettyJson(o.content)
            : prettyJson(o);
      out.push({
        kind: "tool_result",
        text: raw,
        toolUseId: typeof o.tool_use_id === "string" ? o.tool_use_id : undefined,
      });
      continue;
    }

    const toolName =
      (typeof o.name === "string" && o.name && type !== "text" ? o.name : null) ||
      (type === "tool_use" || type === "function" || type === "tool_call"
        ? typeof o.name === "string"
          ? o.name
          : typeof asRecord(o.function)?.name === "string"
            ? String(asRecord(o.function)!.name)
            : null
        : null);

    if (toolName) {
      const input =
        o.input ??
        o.arguments ??
        asRecord(o.function)?.arguments ??
        (() => {
          const rest = { ...o };
          delete rest.type;
          delete rest.name;
          delete rest.text;
          delete rest.id;
          return Object.keys(rest).length ? rest : null;
        })();
      out.push({
        kind: "tool_call",
        name: toolName,
        detail: input != null ? prettyJson(input) : "",
      });
      // also keep accompanying text if present on same block
      if (typeof o.text === "string" && o.text.trim()) {
        out.push({ kind: "text", text: o.text });
      }
      continue;
    }

    if (typeof o.text === "string") {
      out.push({ kind: "text", text: o.text });
      continue;
    }
    if (typeof o.content === "string") {
      out.push({ kind: "text", text: o.content });
      continue;
    }
    out.push({ kind: "other", text: prettyJson(o) });
  }
  return out;
}

function roleKind(role: string): TimelineRow["kind"] {
  const r = role.toLowerCase();
  if (r === "system") return "system";
  if (r === "user") return "user";
  if (r === "assistant") return "assistant";
  if (r === "tool") return "tool";
  return "other";
}

function roleTitle(
  kind: TimelineRow["kind"],
  toolNames: string[],
  isRuntimeContext: boolean,
): string {
  if (isRuntimeContext) return "运行时上下文（平台注入，非用户手打）";
  if (kind === "system") return "系统提示";
  if (kind === "user") return "用户输入";
  if (kind === "assistant") {
    if (toolNames.length) return `模型输出（含工具调用：${toolNames.join(", ")}）`;
    return "模型输出（回复）";
  }
  if (kind === "tool") {
    if (toolNames.length) return `工具回传（${toolNames.join(", ")}）`;
    return "工具回传";
  }
  return kind;
}

export function messagesFromPayload(payload: unknown): unknown[] {
  if (Array.isArray(payload)) return payload;
  const o = asRecord(payload);
  if (o && Array.isArray(o.messages)) return o.messages;
  return [];
}

export function toolsFromPayload(payload: unknown): unknown[] {
  const o = asRecord(payload);
  if (o && Array.isArray(o.tools)) return o.tools;
  return [];
}

export function buildTimeline(messages: unknown[]): TimelineRow[] {
  return messages.map((msg, index) => {
    const o = asRecord(msg);
    const role = o && typeof o.role === "string" ? o.role : "unknown";
    const kind = roleKind(role);
    const blocks = contentBlocks(o?.content);
    let segments = parseSegments(blocks);
    if (!segments.length && o) {
      segments = [{ kind: "other", text: prettyJson(o) }];
    }
    const toolNames = segments
      .filter((s): s is Extract<ContentSegment, { kind: "tool_call" }> => s.kind === "tool_call")
      .map((s) => s.name);
    if (kind === "tool" && !toolNames.length && o && typeof o.name === "string") {
      toolNames.push(o.name);
    }
    const firstText = segments.find((s) => s.kind === "text" || s.kind === "tool_result");
    const textProbe =
      firstText && (firstText.kind === "text" || firstText.kind === "tool_result")
        ? firstText.text
        : "";
    const isRuntimeContext =
      kind === "user" && textProbe.trimStart().startsWith("[runtime_context]");
    return {
      index,
      role,
      kind,
      title: roleTitle(kind, toolNames, isRuntimeContext),
      toolNames,
      isRuntimeContext,
      segments,
    };
  });
}

export function toolCatalogNames(tools: unknown[]): string[] {
  const names: string[] = [];
  for (const t of tools) {
    const o = asRecord(t);
    if (o && typeof o.name === "string") names.push(o.name);
  }
  return names;
}

export function roleBadgeClass(kind: TimelineRow["kind"]): string {
  switch (kind) {
    case "system":
      return "border-border bg-muted text-muted-foreground";
    case "user":
      return "border-primary/30 bg-primary/10 text-foreground";
    case "assistant":
      return "border-success/40 bg-success/10 text-foreground";
    case "tool":
      return "border-warning/40 bg-warning/10 text-foreground";
    default:
      return "border-border bg-card text-muted-foreground";
  }
}
