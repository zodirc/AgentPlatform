/**
 * 工具审批 UI 辅助：按工具类型生成文案、解析事件、提取命令前缀。
 */

/** 待审批工具的分类，用于差异化展示批准按钮与说明。 */
export type ApprovalToolKind =
  | "write_file"
  | "run_command"
  | "edit_file"
  | "run_tests"
  | "generic";

/**
 * 将后端 tool_name 映射为审批 UI 分类。
 * @param toolName 工具名称，未知时归为 generic
 * @returns 审批展示用的工具类别
 */
export function approvalToolKind(
  toolName: string | null | undefined,
): ApprovalToolKind {
  const name = toolName ?? "";
  if (name === "write_file") return "write_file";
  if (name === "run_command") return "run_command";
  if (name === "edit_file") return "edit_file";
  if (name === "run_tests") return "run_tests";
  return "generic";
}

/**
 * 按工具类型返回审批横幅的标题、说明与批准按钮文案。
 * @param toolName 待审批工具名
 * @returns 面向用户的审批 UI 文案
 */
export function approvalCopy(toolName: string | null | undefined): {
  title: string;
  description: string;
  approveLabel: string;
} {
  const kind = approvalToolKind(toolName);
  if (kind === "write_file") {
    return {
      title: "待审批：写文件",
      description:
        "Agent 要把内容写入磁盘。批准后，本回合内后续写盘/编辑将不再询问（Shell 命令仍单独审批）。",
      approveLabel: "批准写文件（本回合后续免批）",
    };
  }
  if (kind === "run_command") {
    return {
      title: "待审批：执行命令",
      description:
        "批准这次只放行当前命令。加入允许列表后，相同前缀的后续命令不再询问（可在设置中删除）。",
      approveLabel: "批准这次",
    };
  }
  if (kind === "edit_file") {
    return {
      title: "待审批：编辑文件",
      description:
        "Agent 要修改已有文件。批准后，本回合内后续写盘/编辑将不再询问（Shell 命令仍单独审批）。",
      approveLabel: "批准编辑（本回合后续免批）",
    };
  }
  if (kind === "run_tests") {
    return {
      title: "待审批：运行测试",
      description: "Agent 要运行测试命令，需要你批准才会执行。",
      approveLabel: "批准运行测试",
    };
  }
  return {
    title: "待审批工具调用",
    description: "Agent 要执行敏感操作，需要你批准才会继续。",
    approveLabel: "批准",
  };
}

/**
 * 从事件流中找出尚未被 approval.resolved 消掉的最后一次 approval.requested。
 * @param events 回合事件列表（按时间顺序）
 * @returns 仍待处理的审批请求事件，若无则 undefined
 */
export function lastApprovalEvent<
  T extends { type: string; payload?: Record<string, unknown> },
>(events: T[]): T | undefined {
  let pending: T | undefined;
  for (const event of events) {
    if (event.type === "approval.requested") {
      pending = event;
      continue;
    }
    if (event.type !== "approval.resolved" || !pending) continue;
    const pendingId = String(pending.payload?.tool_call_id ?? "");
    const resolvedId = String(event.payload?.tool_call_id ?? "");
    if (!resolvedId || !pendingId || resolvedId === pendingId) {
      pending = undefined;
    }
  }
  return pending;
}

/**
 * 审批条一行摘要：命令类显示 command，文件类显示 path。
 * @param toolName 工具名
 * @param args 工具调用参数
 * @param path 可选的文件路径（优先于 args.path）
 * @returns 单行展示文本
 */
export function approvalDetailLine(
  toolName: string | null | undefined,
  args: Record<string, unknown> | undefined,
  path?: string,
): string {
  const command = typeof args?.command === "string" ? args.command.trim() : "";
  const resolvedPath =
    (path ?? "").trim() ||
    (typeof args?.path === "string" ? args.path.trim() : "");
  if ((toolName ?? "") === "run_command" && command) return command;
  return resolvedPath || (toolName ?? "").trim();
}

/**
 * 从 shell 命令提取首个 token，作为「加入允许列表」的默认前缀。
 * @param command 完整命令字符串
 * @returns 首个词（空白归一化后），空命令返回 ""
 */
export function defaultPrefixFromCommand(command: string): string {
  const norm = command.replace(/\s+/g, " ").trim();
  if (!norm) return "";
  return norm.split(" ")[0] ?? "";
}
