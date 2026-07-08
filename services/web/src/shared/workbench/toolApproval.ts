export type ApprovalToolKind = "write_file" | "run_command" | "edit_file" | "run_tests" | "generic";

export function approvalToolKind(toolName: string | null | undefined): ApprovalToolKind {
  const name = toolName ?? "";
  if (name === "write_file") return "write_file";
  if (name === "run_command") return "run_command";
  if (name === "edit_file") return "edit_file";
  if (name === "run_tests") return "run_tests";
  return "generic";
}

export function approvalCopy(toolName: string | null | undefined): {
  title: string;
  description: string;
  approveLabel: string;
} {
  const kind = approvalToolKind(toolName);
  if (kind === "write_file") {
    return {
      title: "待审批：写文件",
      description: "Agent 要把内容写入磁盘，需要你批准才会执行。",
      approveLabel: "批准写文件",
    };
  }
  if (kind === "run_command") {
    return {
      title: "待审批：执行命令",
      description: "Agent 要在工作区运行 Shell 命令（不是写文件）。批准后命令会立即执行。",
      approveLabel: "批准执行命令",
    };
  }
  if (kind === "edit_file") {
    return {
      title: "待审批：编辑文件",
      description: "Agent 要修改已有文件内容，需要你批准才会执行。",
      approveLabel: "批准编辑",
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

export function lastApprovalEvent<T extends { type: string }>(
  events: T[],
): T | undefined {
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (events[i]?.type === "approval.requested") return events[i];
  }
  return undefined;
}
