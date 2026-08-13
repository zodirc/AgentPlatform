/** User-facing copy for pull-dispatch / turn failure maturity (O1/O3/O4). */

const ADMISSION_REASONS: Record<string, string> = {
  dispatch_queue_full: "系统繁忙，排队已满，请稍后重试",
  per_tenant_queue_full: "你的任务排队已满，请稍后再发",
};

const TERMINATION_COPY: Record<string, string> = {
  start_timeout: "暂时没有可用执行器领取任务，请重试",
  runner_lost: "执行器异常断开，任务已中止，请重试",
  db_timeout: "数据库超时，请稍后重试",
  budget_exceeded: "执行容量已满，请稍后重试",
  start_failed: "无法启动任务，请稍后重试",
  approval_state_lost: "审批状态已失效，请重新发起",
  approval_resume_timeout: "审批等待超时，请重新发起",
  model_timeout: "模型响应超时，请重试",
  step_timeout: "步骤执行超时，请重试",
  fatal_error: "任务失败，请重试",
};

export class ApiHttpError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly retryAfterSeconds: number | null;
  readonly code: string | null;

  constructor(opts: {
    status: number;
    detail: string;
    retryAfterSeconds?: number | null;
    code?: string | null;
  }) {
    super(opts.detail);
    this.name = "ApiHttpError";
    this.status = opts.status;
    this.detail = opts.detail;
    this.retryAfterSeconds = opts.retryAfterSeconds ?? null;
    this.code = opts.code ?? null;
  }
}

function parseRetryAfter(header: string | null): number | null {
  if (!header) return null;
  const asInt = Number.parseInt(header.trim(), 10);
  if (Number.isFinite(asInt) && asInt >= 0) return asInt;
  const when = Date.parse(header);
  if (Number.isFinite(when)) {
    return Math.max(0, Math.ceil((when - Date.now()) / 1000));
  }
  return null;
}

async function readErrorDetail(res: Response): Promise<{
  detail: string;
  code: string | null;
}> {
  const fallback = `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as {
      detail?: unknown;
      error?: { message?: string; code?: string };
    };
    if (typeof body.detail === "string" && body.detail.trim()) {
      return { detail: body.detail.trim(), code: null };
    }
    if (body.error?.message) {
      return {
        detail: String(body.error.message),
        code: body.error.code ? String(body.error.code) : null,
      };
    }
  } catch {
    // ignore non-JSON
  }
  return { detail: fallback, code: null };
}

export async function throwIfNotOk(
  res: Response,
  fallbackContext: string,
): Promise<void> {
  if (res.ok) return;
  const { detail, code } = await readErrorDetail(res);
  const retryAfterSeconds = parseRetryAfter(res.headers.get("Retry-After"));
  const friendly =
    res.status === 429
      ? ADMISSION_REASONS[detail] ||
        (retryAfterSeconds != null
          ? `请求过多，请约 ${retryAfterSeconds}s 后重试`
          : "请求过多，请稍后重试")
      : res.status === 502
        ? TERMINATION_COPY.start_failed
        : detail;
  throw new ApiHttpError({
    status: res.status,
    detail: friendly || `${fallbackContext}: ${res.status}`,
    retryAfterSeconds,
    code,
  });
}

export function turnFailureUserMessage(
  terminationReason: unknown,
  message?: unknown,
): string {
  const reason = String(terminationReason ?? "").trim();
  const msg = String(message ?? "").trim();
  if (reason && TERMINATION_COPY[reason]) {
    return TERMINATION_COPY[reason];
  }
  if (msg) return msg;
  if (reason) return reason;
  return "未知错误";
}

export function formatSendFailure(err: unknown): string {
  if (err instanceof ApiHttpError) {
    if (err.status === 429 && err.retryAfterSeconds != null) {
      return `${err.detail}（约 ${err.retryAfterSeconds}s）`;
    }
    return err.detail;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}
