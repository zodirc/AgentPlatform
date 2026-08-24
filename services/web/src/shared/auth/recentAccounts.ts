/**
 * 登录页「最近账号」芯片：仅持久化用户名，不存密码。
 */

const STORAGE_KEY = "agent.auth.recent_usernames";
const MAX_RECENT = 5;

/**
 * 读取 localStorage 中最近使用的用户名列表。
 * @returns 最多 MAX_RECENT 条，解析失败返回 []
 */
export function readRecentUsernames(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((v): v is string => typeof v === "string" && v.trim().length > 0)
      .map((v) => v.trim())
      .slice(0, MAX_RECENT);
  } catch {
    return [];
  }
}

/**
 * 将成功登录的用户名插入最近列表头部（大小写去重）。
 * @param username 用户名
 */
export function rememberUsername(username: string): void {
  const cleaned = username.trim();
  if (!cleaned) return;
  const next = [
    cleaned,
    ...readRecentUsernames().filter(
      (u) => u.toLowerCase() !== cleaned.toLowerCase(),
    ),
  ].slice(0, MAX_RECENT);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
}
