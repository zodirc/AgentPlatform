import type { ScenarioId } from "./types";

export type SlashCommandId =
  | "help"
  | "version"
  | "compact"
  | "verify"
  | "polish"
  | "outline"
  | "test"
  | "lint";

export type SlashCommand = {
  id: SlashCommandId;
  /** Inserted text, usually `/name` or `/name ` when args are expected. */
  insert: string;
  label: string;
  description: string;
  /** Scenarios that list this command. Empty = all. */
  scenarios?: ScenarioId[];
};

/** Mirrors runtime Intake slash surface (input_compiler / should_query). */
export const SLASH_COMMANDS: SlashCommand[] = [
  {
    id: "help",
    insert: "/help",
    label: "/help",
    description: "查看可用命令（本地短路，不调模型）",
  },
  {
    id: "version",
    insert: "/version",
    label: "/version",
    description: "显示平台版本",
  },
  {
    id: "compact",
    insert: "/compact",
    label: "/compact",
    description: "压缩会话上下文，节省后续用量",
  },
  {
    id: "verify",
    insert: "/verify",
    label: "/verify",
    description: "核对草稿/导出中的引用（不改文稿）",
  },
  {
    id: "polish",
    insert: "/polish ",
    label: "/polish",
    description: "润色文风节奏（不改情节；不搜资料）",
    scenarios: ["writing", "intel"],
  },
  {
    id: "outline",
    insert: "/outline ",
    label: "/outline",
    description: "只改大纲 outline.md，不写正文",
    scenarios: ["writing", "intel"],
  },
  {
    id: "test",
    insert: "/test ",
    label: "/test",
    description: "运行项目测试并报告失败项",
    scenarios: ["agent", "collab"],
  },
  {
    id: "lint",
    insert: "/lint ",
    label: "/lint",
    description: "读取诊断并修复本轮引入的问题",
    scenarios: ["agent", "collab"],
  },
];

/**
 * Active slash query at the start of the composer.
 * Returns null when not in slash-menu mode (e.g. normal prose, or after a space).
 */
export function slashQueryFromInput(value: string): string | null {
  const match = value.match(/^\s*\/([^\s]*)$/);
  if (!match) return null;
  return match[1] ?? "";
}

export function filterSlashCommands(
  query: string,
  scenarioId: ScenarioId,
  commands: SlashCommand[] = SLASH_COMMANDS,
): SlashCommand[] {
  const q = query.toLowerCase();
  return commands.filter((cmd) => {
    if (cmd.scenarios && !cmd.scenarios.includes(scenarioId)) return false;
    if (!q) return true;
    return (
      cmd.id.startsWith(q) ||
      cmd.label.slice(1).toLowerCase().startsWith(q) ||
      cmd.description.toLowerCase().includes(q)
    );
  });
}
