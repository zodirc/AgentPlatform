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
  md: { Icon: FileText, className: "text-primary" },
  mdx: { Icon: FileText, className: "text-primary" },
  txt: { Icon: FileText, className: "text-muted-foreground" },
  py: { Icon: FileCode2, className: "text-warning" },
  ts: { Icon: FileCode2, className: "text-primary" },
  tsx: { Icon: FileCode2, className: "text-primary" },
  js: { Icon: FileCode2, className: "text-warning" },
  jsx: { Icon: FileCode2, className: "text-warning" },
  json: { Icon: FileJson2, className: "text-warning" },
  yaml: { Icon: Settings2, className: "text-primary" },
  yml: { Icon: Settings2, className: "text-primary" },
  toml: { Icon: Settings2, className: "text-primary" },
  sh: { Icon: Terminal, className: "text-success" },
  bash: { Icon: Terminal, className: "text-success" },
  zsh: { Icon: Terminal, className: "text-success" },
  go: { Icon: FileCode2, className: "text-primary" },
  rs: { Icon: FileCode2, className: "text-destructive" },
  sql: { Icon: Braces, className: "text-destructive" },
  html: { Icon: FileCode2, className: "text-warning" },
  css: { Icon: FileCode2, className: "text-primary" },
  png: { Icon: Image, className: "text-primary" },
  jpg: { Icon: Image, className: "text-primary" },
  jpeg: { Icon: Image, className: "text-primary" },
  gif: { Icon: Image, className: "text-primary" },
  svg: { Icon: Image, className: "text-primary" },
  webp: { Icon: Image, className: "text-primary" },
};

const SPECIAL_NAMES: Record<string, FileIconSpec> = {
  dockerfile: { Icon: FileCode2, className: "text-primary" },
  makefile: { Icon: Terminal, className: "text-foreground/90" },
  "readme.md": { Icon: FileText, className: "text-primary" },
};

export function workspaceEntryIcon(
  name: string,
  isDir: boolean,
  expanded = false,
): FileIconSpec {
  if (isDir) {
    return expanded
      ? { Icon: FolderOpen, className: "text-warning" }
      : { Icon: Folder, className: "text-warning" };
  }

  const lower = name.toLowerCase();
  if (SPECIAL_NAMES[lower]) return SPECIAL_NAMES[lower];

  const dot = lower.lastIndexOf(".");
  const ext = dot >= 0 ? lower.slice(dot + 1) : "";
  if (ext && EXT_ICONS[ext]) return EXT_ICONS[ext];

  return { Icon: File, className: "text-muted-foreground" };
}

export function workspaceEntryIconSizeClass(depth: number): string {
  return depth === 0 ? "h-4 w-4" : "h-3.5 w-3.5";
}
