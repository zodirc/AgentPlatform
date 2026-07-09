import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { fetchWorkspaceEntries } from "../../shared/api/client";
import {
  workspaceEntryIcon,
  workspaceEntryIconSizeClass,
} from "./workspaceFileIcon";

const HIDDEN_ENTRIES = new Set([".ruff_cache", "__pycache__", ".git"]);

function joinPath(parent: string, name: string): string {
  if (parent === "." || parent === "") return name;
  return `${parent.replace(/\/$/, "")}/${name}`;
}

function parseEntries(
  parentPath: string,
  entries: string[],
): Array<{ name: string; path: string; isDir: boolean }> {
  return entries
    .filter((entry) => {
      const name = entry.endsWith("/") ? entry.slice(0, -1) : entry;
      return !HIDDEN_ENTRIES.has(name);
    })
    .map((entry) => {
      const isDir = entry.endsWith("/");
      const name = isDir ? entry.slice(0, -1) : entry;
      return {
        name,
        path: joinPath(parentPath, name),
        isDir,
      };
    })
    .sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
}

type TreeNodeProps = {
  path: string;
  name: string;
  isDir: boolean;
  depth: number;
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
  onOpenFile: (path: string) => void;
};

function TreeNode({
  path,
  name,
  isDir,
  depth,
  selectedPath,
  onSelectFile,
  onOpenFile,
}: TreeNodeProps) {
  const [expanded, setExpanded] = useState(depth === 0);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["workspace-entries", path],
    queryFn: () => fetchWorkspaceEntries(path),
    enabled: isDir && expanded,
    staleTime: 10_000,
  });

  const children = data ? parseEntries(path, data.entries) : [];
  const selected = !isDir && selectedPath === path;
  const { Icon, className: iconClass } = workspaceEntryIcon(
    name === "." ? "workspace" : name,
    isDir,
    expanded,
  );
  const iconSize = workspaceEntryIconSizeClass(depth);

  if (!isDir) {
    return (
      <button
        type="button"
        className={`flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-xs ${
          selected
            ? "bg-sky-900/40 text-sky-200"
            : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
        }`}
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
        onClick={() => onSelectFile(path)}
        onDoubleClick={() => onOpenFile(path)}
        title="双击在新窗口查看"
      >
        <Icon className={`shrink-0 ${iconSize} ${iconClass}`} aria-hidden />
        <span className="truncate">{name}</span>
      </button>
    );
  }

  return (
    <div>
      <button
        type="button"
        className="flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left text-xs text-slate-300 hover:bg-slate-900"
        style={{ paddingLeft: `${depth * 12 + 4}px` }}
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="shrink-0 w-3 text-[10px] text-slate-500">
          {expanded ? "▾" : "▸"}
        </span>
        <Icon className={`shrink-0 ${iconSize} ${iconClass}`} aria-hidden />
        <span className="truncate">{name === "." ? "workspace" : name}</span>
      </button>
      {expanded ? (
        <div>
          {isLoading ? (
            <p
              className="py-1 text-[10px] text-slate-600"
              style={{ paddingLeft: `${(depth + 1) * 12 + 20}px` }}
            >
              加载中…
            </p>
          ) : null}
          {isError ? (
            <p
              className="py-1 text-[10px] text-rose-400"
              style={{ paddingLeft: `${(depth + 1) * 12 + 20}px` }}
            >
              无法读取目录
            </p>
          ) : null}
          {children.map((child) => (
            <TreeNode
              key={child.path}
              path={child.path}
              name={child.name}
              isDir={child.isDir}
              depth={depth + 1}
              selectedPath={selectedPath}
              onSelectFile={onSelectFile}
              onOpenFile={onOpenFile}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

type Props = {
  selectedPath: string | null;
  onSelectFile: (path: string) => void;
  onOpenFile: (path: string) => void;
};

export function WorkspaceTree({
  selectedPath,
  onSelectFile,
  onOpenFile,
}: Props) {
  const handleOpen = useCallback(
    (path: string) => onOpenFile(path),
    [onOpenFile],
  );
  const handleSelect = useCallback(
    (path: string) => onSelectFile(path),
    [onSelectFile],
  );

  return (
    <div>
      <TreeNode
        path="."
        name="workspace"
        isDir
        depth={0}
        selectedPath={selectedPath}
        onSelectFile={handleSelect}
        onOpenFile={handleOpen}
      />
    </div>
  );
}
