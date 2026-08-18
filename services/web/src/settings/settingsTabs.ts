export type SettingsTab =
  | "account"
  | "appearance"
  | "model"
  | "index"
  | "signals"
  | "allowlist";

export const SETTINGS_TABS: { id: SettingsTab; to: string; label: string }[] = [
  { id: "account", to: "/settings", label: "账户" },
  { id: "appearance", to: "/settings/appearance", label: "外观" },
  { id: "model", to: "/settings/model", label: "模型" },
  { id: "index", to: "/settings/index", label: "索引" },
  { id: "allowlist", to: "/settings/allowlist", label: "命令允许" },
  { id: "signals", to: "/settings/signals", label: "体验信号" },
];

export function tabFromPath(pathname: string): SettingsTab {
  if (pathname.endsWith("/model")) return "model";
  if (pathname.endsWith("/appearance")) return "appearance";
  if (pathname.endsWith("/signals")) return "signals";
  if (pathname.endsWith("/index")) return "index";
  if (pathname.endsWith("/allowlist")) return "allowlist";
  return "account";
}
