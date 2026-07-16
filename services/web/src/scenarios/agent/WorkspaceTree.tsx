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
  multiSelectMode: boolean;
  checkedPaths: ReadonlySet<string>;
  onSelectFile: (path: string) => void;
  onOpenFile: (path: string) => void;
  onTogglePath: (path: string) => void;
  onOpenSourcesLibrary?: () => void;
};

function TreeNode({
  path,
  name,
  isDir,
  depth,
  selectedPath,
  multiSelectMode,
  checkedPaths,
  onSelectFile,
  onOpenFile,
  onTogglePath,
  onOpenSourcesLibrary,
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
  const checked = checkedPaths.has(path);
  const deletable = path !== ".";
  const { Icon, className: iconClass } = workspaceEntryIcon(
    name === "." ? "workspace" : name,
    isDir,
    expanded,
  );
  const iconSize = workspaceEntryIconSizeClass(depth);
  const pad = { paddingLeft: `${depth * 12 + 4}px` };

  const checkbox =
    multiSelectMode && deletable ? (
      <input
        type="checkbox"
        className="size-3 shrink-0 rounded border-slate-600 bg-slate-900 accent-sky-500"
        checked={checked}
        onChange={() => onTogglePath(path)}
        onClick={(event) => event.stopPropagation()}
        aria-label={`选择 ${name}`}
      />
    ) : (
      <span className="size-3 shrink-0" aria-hidden />
    );

  if (!isDir) {
    return (
      <div className="flex items-center gap-1" style={pad}>
        {checkbox}
        <button
          type="button"
          className={`min-w-0 flex-1 rounded px-1 py-0.5 text-left text-xs ${
            selected && !multiSelectMode
              ? "bg-sky-900/40 text-sky-200"
              : checked
                ? "bg-rose-950/40 text-rose-200"
                : "text-slate-400 hover:bg-slate-900 hover:text-slate-200"
          }`}
          onClick={() =>
            multiSelectMode ? onTogglePath(path) : onSelectFile(path)
          }
          onDoubleClick={() => {
            if (!multiSelectMode) onOpenFile(path);
          }}
          title={multiSelectMode ? "点击切换选中" : "双击在新窗口查看"}
        >
          <span className="flex items-center gap-1.5">
            <Icon
              className={`shrink-0 ${iconSize} ${iconClass}`}
              aria-hidden
            />
            <span className="truncate">{name}</span>
          </span>
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center gap-1" style={pad}>
        {checkbox}
        <button
          type="button"
          className={`min-w-0 flex-1 rounded px-1 py-0.5 text-left text-xs ${
            checked
              ? "bg-rose-950/40 text-rose-200"
              : "text-slate-300 hover:bg-slate-900"
          }`}
          onClick={() => {
            if (multiSelectMode && deletable) {
              onTogglePath(path);
              return;
            }
            setExpanded((v) => !v);
          }}
          onDoubleClick={() => {
            if (multiSelectMode) return;
            if (path === "sources" && onOpenSourcesLibrary) {
              onOpenSourcesLibrary();
            }
          }}
          title={
            multiSelectMode
              ? "点击切换选中"
              : path === "sources" && onOpenSourcesLibrary
                ? "双击打开资料库"
                : undefined
          }
        >
          <span className="flex items-center gap-1.5">
            <span className="shrink-0 w-3 text-[10px] text-slate-500">
              {expanded ? "▾" : "▸"}
            </span>
            <Icon
              className={`shrink-0 ${iconSize} ${iconClass}`}
              aria-hidden
            />
            <span className="truncate">{name === "." ? "workspace" : name}</span>
          </span>
        </button>
      </div>
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
              multiSelectMode={multiSelectMode}
              checkedPaths={checkedPaths}
              onSelectFile={onSelectFile}
              onOpenFile={onOpenFile}
              onTogglePath={onTogglePath}
              onOpenSourcesLibrary={onOpenSourcesLibrary}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

type Props = {
  selectedPath: string | null;
  multiSelectMode?: boolean;
  checkedPaths?: ReadonlySet<string>;
  onSelectFile: (path: string) => void;
  onOpenFile: (path: string) => void;
  onTogglePath?: (path: string) => void;
  onOpenSourcesLibrary?: () => void;
};

export function WorkspaceTree({
  selectedPath,
  multiSelectMode = false,
  checkedPaths = new Set(),
  onSelectFile,
  onOpenFile,
  onTogglePath,
  onOpenSourcesLibrary,
}: Props) {
  const handleOpen = useCallback(
    (path: string) => onOpenFile(path),
    [onOpenFile],
  );
  const handleSelect = useCallback(
    (path: string) => onSelectFile(path),
    [onSelectFile],
  );
  const handleToggle = useCallback(
    (path: string) => onTogglePath?.(path),
    [onTogglePath],
  );

  return (
    <div>
      <TreeNode
        path="."
        name="workspace"
        isDir
        depth={0}
        selectedPath={selectedPath}
        multiSelectMode={multiSelectMode}
        checkedPaths={checkedPaths}
        onSelectFile={handleSelect}
        onOpenFile={handleOpen}
        onTogglePath={handleToggle}
        onOpenSourcesLibrary={onOpenSourcesLibrary}
      />
    </div>
  );
}
