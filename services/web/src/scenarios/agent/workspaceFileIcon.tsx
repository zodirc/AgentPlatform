import type { LucideIcon } from "lucide-react";
import {
  Braces,
  File,
  FileCode2,
  FileJson2,
  FileText,
  Folder,
  FolderOpen,
  Image,
  Settings2,
  Terminal,
} from "lucide-react";

export type FileIconSpec = {
  Icon: LucideIcon;
  className: string;
};

const EXT_ICONS: Record<string, FileIconSpec> = {
  md: { Icon: FileText, className: "text-sky-400" },
  mdx: { Icon: FileText, className: "text-sky-400" },
  txt: { Icon: FileText, className: "text-slate-400" },
  py: { Icon: FileCode2, className: "text-yellow-400" },
  ts: { Icon: FileCode2, className: "text-blue-400" },
  tsx: { Icon: FileCode2, className: "text-sky-300" },
  js: { Icon: FileCode2, className: "text-amber-300" },
  jsx: { Icon: FileCode2, className: "text-amber-300" },
  json: { Icon: FileJson2, className: "text-amber-400" },
  yaml: { Icon: Settings2, className: "text-violet-400" },
  yml: { Icon: Settings2, className: "text-violet-400" },
  toml: { Icon: Settings2, className: "text-violet-400" },
  sh: { Icon: Terminal, className: "text-emerald-400" },
  bash: { Icon: Terminal, className: "text-emerald-400" },
  zsh: { Icon: Terminal, className: "text-emerald-400" },
  go: { Icon: FileCode2, className: "text-cyan-400" },
  rs: { Icon: FileCode2, className: "text-orange-400" },
  sql: { Icon: Braces, className: "text-pink-400" },
  html: { Icon: FileCode2, className: "text-orange-300" },
  css: { Icon: FileCode2, className: "text-blue-300" },
  png: { Icon: Image, className: "text-purple-400" },
  jpg: { Icon: Image, className: "text-purple-400" },
  jpeg: { Icon: Image, className: "text-purple-400" },
  gif: { Icon: Image, className: "text-purple-400" },
  svg: { Icon: Image, className: "text-purple-400" },
  webp: { Icon: Image, className: "text-purple-400" },
};

const SPECIAL_NAMES: Record<string, FileIconSpec> = {
  dockerfile: { Icon: FileCode2, className: "text-blue-400" },
  makefile: { Icon: Terminal, className: "text-slate-300" },
  "readme.md": { Icon: FileText, className: "text-sky-400" },
};

export function workspaceEntryIcon(
  name: string,
  isDir: boolean,
  expanded = false,
): FileIconSpec {
  if (isDir) {
    return expanded
      ? { Icon: FolderOpen, className: "text-amber-400" }
      : { Icon: Folder, className: "text-amber-400" };
  }

  const lower = name.toLowerCase();
  if (SPECIAL_NAMES[lower]) return SPECIAL_NAMES[lower];

  const dot = lower.lastIndexOf(".");
  const ext = dot >= 0 ? lower.slice(dot + 1) : "";
  if (ext && EXT_ICONS[ext]) return EXT_ICONS[ext];

  return { Icon: File, className: "text-slate-500" };
}

export function workspaceEntryIconSizeClass(depth: number): string {
  return depth === 0 ? "h-4 w-4" : "h-3.5 w-3.5";
}
