import { ApiHttpError } from "../api/httpErrors";

export function messageForAuthFailure(
  err: unknown,
  mode: "login" | "register",
): string {
  if (err instanceof TypeError) {
    return "无法连接服务器，请稍后再试";
  }
  const status = err instanceof ApiHttpError ? err.status : undefined;
  if (status === 401) {
    return mode === "login" ? "用户名或密码不正确" : "注册失败，请检查输入";
  }
  if (status === 409) {
    return "用户名已被占用";
  }
  if (status === 429) {
    return err instanceof ApiHttpError && err.detail
      ? err.detail
      : "尝试过于频繁，请稍后再试";
  }
  if (status != null && status >= 500) {
    return "服务暂时不可用，请稍后再试";
  }
  return mode === "login"
    ? "登录失败，请稍后再试"
    : "注册失败，用户名可能已占用";
}
