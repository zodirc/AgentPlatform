import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FilePlus, FolderPlus } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  downloadWorkspaceFile,
  fetchWorkspaceEntries,
  type WorkspaceEntries,
} from "../../shared/api/client";
import { isSeedCorpusPath } from "../../shared/workspace/seedPath";
import { isWorkSurfaceHiddenPath } from "../../shared/workspace/harnessPath";
import {
  workspaceEntryIcon,
  workspaceEntryIconSizeClass,
} from "./workspaceFileIcon";
import {
  joinWorkspacePath,
  parentDirOf,
  toWorkspaceRelativePath,
  isPathChecked,
} from "./workspacePaths";

export {
  joinWorkspacePath,
  parentDirOf,
  toWorkspaceRelativePath,
} from "./workspacePaths";

const HIDDEN_ENTRIES = new Set([
  ".ruff_cache",
  "__pycache__",
  ".git",
  ".agent",
]);

const TREE_STALE_MS = 120_000;

function parseEntries(
  parentPath: string,
  entries: string[],
): Array<{ name: string; path: string; isDir: boolean }> {
  return entries
    .filter((entry) => {
      const name = entry.endsWith("/") ? entry.slice(0, -1) : entry;
      if (HIDDEN_ENTRIES.has(name)) return false;
      const full = joinWorkspacePath(parentPath, name);
      return !isWorkSurfaceHiddenPath(full);
    })
    .map((entry) => {
      const isDir = entry.endsWith("/");
      const name = isDir ? entry.slice(0, -1) : entry;
      return {
        name,
        path: joinWorkspacePath(parentPath, name),
        isDir,
      };
    })
    .sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
}

/** Optimistically insert a child into a directory listing cache. */
export function patchWorkspaceEntriesCache(
  queryClient: ReturnType<typeof useQueryClient>,
  parentDir: string,
  entryName: string,
  isDir: boolean,
) {
  const key = ["workspace-entries", parentDir] as const;
  const marker = isDir ? `${entryName}/` : entryName;
  queryClient.setQueryData<WorkspaceEntries>(key, (prev) => {
    if (!prev) {
      return { path: parentDir, entries: [marker] };
    }
    if (prev.entries.some((e) => e === marker || e === entryName || e === `${entryName}/`)) {
      return prev;
    }
    return { ...prev, entries: [...prev.entries, marker] };
  });
}

export function removeWorkspaceEntryFromCache(
  queryClient: ReturnType<typeof useQueryClient>,
  parentDir: string,
  entryName: string,
) {
  const key = ["workspace-entries", parentDir] as const;
  queryClient.setQueryData<WorkspaceEntries>(key, (prev) => {
    if (!prev) return prev;
    return {
      ...prev,
      entries: prev.entries.filter(
        (e) => e !== entryName && e !== `${entryName}/`,
      ),
    };
  });
}

type ContextTarget = {
  path: string;
  name: string;
  isDir: boolean;
  x: number;
  y: number;
};

type InlineDraft =
  | {
      kind: "create-file" | "create-folder";
      parentDir: string;
      depth: number;
      seed: string;
    }
  | {
      kind: "rename";
      path: string;
      parentDir: string;
      depth: number;
      seed: string;
      isDir: boolean;
    };

type MenuItem = {
  id: string;
  label: string;
  disabled?: boolean;
  danger?: boolean;
  separator?: boolean;
};

function InlineNameRow({
  depth,
  isDir,
  seed,
  onSubmit,
  onCancel,
}: {
  depth: number;
  isDir: boolean;
  seed: string;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(seed);
  const inputRef = useRef<HTMLInputElement>(null);
  const { Icon, className: iconClass } = workspaceEntryIcon(
    isDir ? "folder" : seed || "file.txt",
    isDir,
    true,
  );
  const iconSize = workspaceEntryIconSizeClass(depth);
  const done = useRef(false);

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    const dot = seed.lastIndexOf(".");
    if (!isDir && dot > 0) el.setSelectionRange(0, dot);
    else el.select();
  }, [seed, isDir]);

  const commit = () => {
    if (done.current) return;
    const name = value.trim();
    if (!name || name.includes("/") || name.includes("\\") || name.includes("..")) {
      onCancel();
      return;
    }
    done.current = true;
    onSubmit(name);
  };

  const cancel = () => {
    if (done.current) return;
    done.current = true;
    onCancel();
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commit();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancel();
    }
  };

  return (
    <div
      className="flex items-center gap-1 py-0.5"
      style={{ paddingLeft: `${depth * 12 + 4 + 16}px` }}
    >
      <Icon className={`shrink-0 ${iconSize} ${iconClass}`} aria-hidden />
      <input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commit}
        className="min-w-0 flex-1 rounded border border-primary/50 bg-background px-1 py-0.5 text-xs text-foreground outline-none ring-1 ring-primary/30"
        aria-label={isDir ? "文件夹名" : "文件名"}
      />
    </div>
  );
}

type TreeNodeProps = {
  path: string;
  name: string;
  isDir: boolean;
  depth: number;
  selectedPath: string | null;
  multiSelectMode: boolean;
  checkedPaths: ReadonlySet<string>;
  cutPath: string | null;
  expandedPaths: ReadonlySet<string>;
  draft: InlineDraft | null;
  renamingPath: string | null;
  onToggleExpand: (path: string) => void;
  onSelectFile: (path: string) => void;
  onOpenFile: (path: string) => void;
  onTogglePath: (path: string, isDir: boolean) => void;
  onOpenSourcesLibrary?: () => void;
  onContextMenu: (target: ContextTarget) => void;
  onDraftSubmit: (name: string) => void;
  onDraftCancel: () => void;
  onActivateDir: (path: string) => void;
};

function TreeNode({
  path,
  name,
  isDir,
  depth,
  selectedPath,
  multiSelectMode,
  checkedPaths,
  cutPath,
  expandedPaths,
  draft,
  renamingPath,
  onToggleExpand,
  onSelectFile,
  onOpenFile,
  onTogglePath,
  onOpenSourcesLibrary,
  onContextMenu,
  onDraftSubmit,
  onDraftCancel,
  onActivateDir,
}: TreeNodeProps) {
  const expanded = isDir && expandedPaths.has(path);
  const { data, isPending, isError, isFetching } = useQuery({
    queryKey: ["workspace-entries", path],
    queryFn: () => fetchWorkspaceEntries(path),
    enabled: isDir && expanded,
    staleTime: TREE_STALE_MS,
    gcTime: 600_000,
    refetchOnWindowFocus: false,
  });

  const children = data ? parseEntries(path, data.entries) : [];
  // Only flash "加载中" on cold load — keep prior rows while background refetching.
  const showColdLoading = isDir && expanded && isPending && !data;
  const selected = selectedPath === path;
  const checked = isPathChecked(checkedPaths, path);
  const cut = cutPath === path;
  const deletable =
    path !== "." && !isSeedCorpusPath(path) && !isWorkSurfaceHiddenPath(path);
  const { Icon, className: iconClass } = workspaceEntryIcon(
    name === "." ? "workspace" : name,
    isDir,
    expanded,
  );
  const iconSize = workspaceEntryIconSizeClass(depth);
  const pad = { paddingLeft: `${depth * 12 + 4}px` };
  const showCreateDraft =
    draft &&
    (draft.kind === "create-file" || draft.kind === "create-folder") &&
    draft.parentDir === path;
  const isRenamingThis = draft?.kind === "rename" && draft.path === path;

  const openContext = (event: ReactMouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    onContextMenu({
      path,
      name: name === "." ? "workspace" : name,
      isDir,
      x: event.clientX,
      y: event.clientY,
    });
  };

  const checkbox =
    multiSelectMode && deletable ? (
      <input
        type="checkbox"
        className="size-3 shrink-0 rounded border-input bg-card accent-primary"
        checked={checked}
        onChange={() => {
          onTogglePath(path, isDir);
          if (isDir && !expanded) onToggleExpand(path);
        }}
        onClick={(event) => event.stopPropagation()}
        aria-label={`选择 ${name}`}
      />
    ) : (
      <span className="size-3 shrink-0" aria-hidden />
    );

  if (!isDir) {
    const seedLocked = isSeedCorpusPath(path);
    if (isRenamingThis && draft?.kind === "rename") {
      return (
        <InlineNameRow
          depth={depth}
          isDir={false}
          seed={draft.seed}
          onSubmit={onDraftSubmit}
          onCancel={onDraftCancel}
        />
      );
    }
    return (
      <div
        className={`flex items-center gap-1 ${isFetching ? "" : ""}`}
        style={pad}
      >
        {checkbox}
        <button
          type="button"
          className={`min-w-0 flex-1 rounded px-1 py-0.5 text-left text-xs ${
            cut || renamingPath === path ? "opacity-50" : ""
          } ${cut ? "line-through" : ""} ${
            selected && !multiSelectMode
              ? "bg-primary/15 text-primary"
              : checked
                ? "bg-destructive/10 text-destructive"
                : seedLocked
                  ? "text-muted-foreground/90 hover:bg-muted"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
          }`}
          onClick={() =>
            multiSelectMode
              ? deletable
                ? onTogglePath(path, false)
                : undefined
              : onSelectFile(path)
          }
          onDoubleClick={() => {
            if (!multiSelectMode) onOpenFile(path);
          }}
          onContextMenu={openContext}
          title={
            seedLocked
              ? "系统资料 · 只读"
              : multiSelectMode
                ? "点击切换选中"
                : "双击打开编辑 · 右键更多操作"
          }
        >
          <span className="flex items-center gap-1.5">
            <Icon
              className={`shrink-0 ${iconSize} ${iconClass}`}
              aria-hidden
            />
            <span className="truncate">{name}</span>
            {seedLocked ? (
              <span className="ml-auto shrink-0 text-[9px] text-muted-foreground/80">
                只读
              </span>
            ) : null}
          </span>
        </button>
        {!multiSelectMode ? (
          <button
            type="button"
            className="shrink-0 rounded p-0.5 text-muted-foreground/70 hover:bg-muted hover:text-foreground"
            title="下载"
            aria-label={`下载 ${name}`}
            onClick={(event) => {
              event.stopPropagation();
              void downloadWorkspaceFile(path);
            }}
          >
            <Download className="h-3 w-3" />
          </button>
        ) : null}
      </div>
    );
  }

  if (isRenamingThis && draft?.kind === "rename") {
    return (
      <div>
        <InlineNameRow
          depth={depth}
          isDir
          seed={draft.seed}
          onSubmit={onDraftSubmit}
          onCancel={onDraftCancel}
        />
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
            cut ? "opacity-50 line-through" : ""
          } ${
            selected && !multiSelectMode
              ? "bg-primary/15 text-primary"
              : checked
                ? "bg-destructive/10 text-destructive"
                : "text-foreground/90 hover:bg-muted"
          }`}
          onClick={() => {
            if (multiSelectMode && deletable) {
              onTogglePath(path, true);
              if (!expanded) onToggleExpand(path);
              return;
            }
            onActivateDir(path);
            onToggleExpand(path);
          }}
          onDoubleClick={() => {
            if (multiSelectMode) return;
            if (path === "sources" && onOpenSourcesLibrary) {
              onOpenSourcesLibrary();
            }
          }}
          onContextMenu={openContext}
          title={
            multiSelectMode
              ? "点击切换选中"
              : path === "sources" && onOpenSourcesLibrary
                ? "双击打开资料库 · 右键更多操作"
                : "右键更多操作"
          }
        >
          <span className="flex items-center gap-1.5">
            <span className="shrink-0 w-3 text-[10px] text-muted-foreground">
              {expanded ? "▾" : "▸"}
            </span>
            <Icon
              className={`shrink-0 ${iconSize} ${iconClass}`}
              aria-hidden
            />
            <span className="truncate">{name === "." ? "workspace" : name}</span>
            {isFetching && data ? (
              <span
                className="ml-auto size-1.5 shrink-0 rounded-full bg-muted-foreground/40"
                title="同步中"
                aria-hidden
              />
            ) : null}
          </span>
        </button>
      </div>
      {expanded ? (
        <div>
          {showColdLoading ? (
            <p
              className="py-1 text-[10px] text-muted-foreground/80"
              style={{ paddingLeft: `${(depth + 1) * 12 + 20}px` }}
            >
              加载中…
            </p>
          ) : null}
          {isError && !data ? (
            <p
              className="py-1 text-[10px] text-destructive"
              style={{ paddingLeft: `${(depth + 1) * 12 + 20}px` }}
            >
              无法读取目录
            </p>
          ) : null}
          {showCreateDraft && draft ? (
            <InlineNameRow
              depth={depth + 1}
              isDir={draft.kind === "create-folder"}
              seed={draft.seed}
              onSubmit={onDraftSubmit}
              onCancel={onDraftCancel}
            />
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
              cutPath={cutPath}
              expandedPaths={expandedPaths}
              draft={draft}
              renamingPath={renamingPath}
              onToggleExpand={onToggleExpand}
              onSelectFile={onSelectFile}
              onOpenFile={onOpenFile}
              onTogglePath={onTogglePath}
              onOpenSourcesLibrary={onOpenSourcesLibrary}
              onContextMenu={onContextMenu}
              onDraftSubmit={onDraftSubmit}
              onDraftCancel={onDraftCancel}
              onActivateDir={onActivateDir}
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
  cutPath?: string | null;
  onSelectFile: (path: string) => void;
  onOpenFile: (path: string) => void;
  onTogglePath?: (path: string, isDir: boolean) => void;
  /** Expand ancestors so newly written / selected-dir children are visible. */
  revealPaths?: readonly string[];
  onOpenSourcesLibrary?: () => void;
  /** Create file at parentDir with leaf name (no prompts). */
  onCommitCreateFile?: (parentDir: string, name: string) => Promise<void> | void;
  onCommitCreateFolder?: (parentDir: string, name: string) => Promise<void> | void;
  onCommitRename?: (path: string, newName: string) => Promise<void> | void;
  onDeletePath?: (path: string) => void;
  onCopyPath?: (path: string) => void;
  onCutPath?: (path: string) => void;
  onPasteInto?: (parentDir: string) => void;
  onDownloadPath?: (path: string) => void;
};

export function WorkspaceTree({
  selectedPath,
  multiSelectMode = false,
  checkedPaths = new Set(),
  cutPath = null,
  onSelectFile,
  onOpenFile,
  onTogglePath,
  revealPaths = [],
  onOpenSourcesLibrary,
  onCommitCreateFile,
  onCommitCreateFolder,
  onCommitRename,
  onDeletePath,
  onCopyPath,
  onCutPath,
  onPasteInto,
  onDownloadPath,
}: Props) {
  const [menu, setMenu] = useState<ContextTarget | null>(null);
  const [draft, setDraft] = useState<InlineDraft | null>(null);
  const [expandedPaths, setExpandedPaths] = useState<Set<string>>(
    () => new Set(["."]),
  );
  const menuRef = useRef<HTMLDivElement>(null);

  const [anchorDir, setAnchorDir] = useState(".");

  const handleOpen = useCallback(
    (path: string) => onOpenFile(path),
    [onOpenFile],
  );
  const handleSelect = useCallback(
    (path: string) => {
      setAnchorDir(parentDirOf(path));
      onSelectFile(path);
    },
    [onSelectFile],
  );
  const handleSelectDir = useCallback(
    (path: string) => {
      setAnchorDir(path);
      onSelectFile(path);
    },
    [onSelectFile],
  );
  const handleToggle = useCallback(
    (path: string, isDir: boolean) => onTogglePath?.(path, isDir),
    [onTogglePath],
  );

  useEffect(() => {
    if (revealPaths.length === 0) return;
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      let changed = false;
      const add = (path: string) => {
        if (next.has(path)) return;
        next.add(path);
        changed = true;
      };
      add(".");
      for (const raw of revealPaths) {
        const rel = toWorkspaceRelativePath(raw);
        if (!rel) continue;
        let acc = ".";
        for (const part of rel.split("/").filter(Boolean)) {
          acc = joinWorkspacePath(acc, part);
          add(acc);
        }
      }
      return changed ? next : prev;
    });
  }, [revealPaths]);

  const toggleExpand = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const ensureExpanded = useCallback((path: string) => {
    setExpandedPaths((prev) => {
      if (prev.has(path)) return prev;
      const next = new Set(prev);
      next.add(path);
      return next;
    });
  }, []);

  const beginCreate = useCallback(
    (kind: "create-file" | "create-folder", parentDir: string) => {
      if (isSeedCorpusPath(parentDir)) {
        window.alert("不能在系统资料目录下新建。");
        return;
      }
      ensureExpanded(parentDir);
      setAnchorDir(parentDir);
      setMenu(null);
      setDraft({
        kind,
        parentDir,
        depth: parentDir === "." ? 1 : parentDir.split("/").length + 1,
        seed: kind === "create-file" ? "untitled.md" : "new-folder",
      });
    },
    [ensureExpanded],
  );

  const beginRename = useCallback(
    (path: string, isDir: boolean) => {
      if (
        path === "." ||
        isSeedCorpusPath(path) ||
        isWorkSurfaceHiddenPath(path)
      ) {
        window.alert("该路径不可重命名。");
        return;
      }
      const leaf = path.split("/").pop() || path;
      setMenu(null);
      setDraft({
        kind: "rename",
        path,
        parentDir: parentDirOf(path),
        depth: path === "." ? 0 : path.split("/").length - 1,
        seed: leaf,
        isDir,
      });
    },
    [],
  );

  useEffect(() => {
    if (!menu) return;
    const close = (event: MouseEvent) => {
      if (menuRef.current?.contains(event.target as Node)) return;
      setMenu(null);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenu(null);
    };
    window.addEventListener("mousedown", close);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);

  const mutableTarget =
    menu &&
    menu.path !== "." &&
    !isSeedCorpusPath(menu.path) &&
    !isWorkSurfaceHiddenPath(menu.path);

  const parentForCreate = menu
    ? menu.isDir
      ? menu.path
      : parentDirOf(menu.path)
    : ".";

  const menuItems: MenuItem[] = menu
    ? [
        { id: "new-file", label: "新建文件" },
        { id: "new-folder", label: "新建文件夹" },
        { id: "sep-1", label: "", separator: true },
        { id: "copy-path", label: "拷贝相对路径", disabled: menu.path === "." },
        { id: "rename", label: "重命名", disabled: !mutableTarget },
        { id: "cut", label: "剪切", disabled: !mutableTarget },
        {
          id: "paste",
          label: cutPath ? "粘贴到此处" : "粘贴",
          disabled: !cutPath || isSeedCorpusPath(parentForCreate),
        },
        ...(menu.isDir
          ? []
          : [{ id: "download", label: "下载" } satisfies MenuItem]),
        { id: "sep-2", label: "", separator: true },
        {
          id: "delete",
          label: "删除",
          disabled: !mutableTarget,
          danger: true,
        },
      ]
    : [];

  const runMenu = (id: string) => {
    if (!menu) return;
    const target = menu;
    setMenu(null);
    switch (id) {
      case "new-file":
        beginCreate("create-file", parentForCreate);
        break;
      case "new-folder":
        beginCreate("create-folder", parentForCreate);
        break;
      case "copy-path":
        onCopyPath?.(target.path);
        break;
      case "rename":
        beginRename(target.path, target.isDir);
        break;
      case "cut":
        onCutPath?.(target.path);
        break;
      case "paste":
        onPasteInto?.(parentForCreate);
        break;
      case "download":
        onDownloadPath?.(target.path);
        break;
      case "delete":
        onDeletePath?.(target.path);
        break;
      default:
        break;
    }
  };

  const onDraftSubmit = async (name: string) => {
    const current = draft;
    setDraft(null);
    if (!current) return;
    try {
      if (current.kind === "create-file") {
        await onCommitCreateFile?.(current.parentDir, name);
      } else if (current.kind === "create-folder") {
        await onCommitCreateFolder?.(current.parentDir, name);
      } else if (current.kind === "rename") {
        await onCommitRename?.(current.path, name);
      }
    } catch {
      // Caller shows alert
    }
  };

  const renamingPath = draft?.kind === "rename" ? draft.path : null;

  return (
    <div className="relative">
      <div className="mb-1.5 flex items-center gap-0.5">
        <button
          type="button"
          className="inline-flex size-6 items-center justify-center rounded border border-input text-muted-foreground hover:bg-muted hover:text-foreground"
          title="新建文件"
          aria-label="新建文件"
          onClick={() => beginCreate("create-file", anchorDir)}
        >
          <FilePlus className="size-3.5" aria-hidden />
        </button>
        <button
          type="button"
          className="inline-flex size-6 items-center justify-center rounded border border-input text-muted-foreground hover:bg-muted hover:text-foreground"
          title="新建文件夹"
          aria-label="新建文件夹"
          onClick={() => beginCreate("create-folder", anchorDir)}
        >
          <FolderPlus className="size-3.5" aria-hidden />
        </button>
      </div>
      <TreeNode
        path="."
        name="workspace"
        isDir
        depth={0}
        selectedPath={selectedPath}
        multiSelectMode={multiSelectMode}
        checkedPaths={checkedPaths}
        cutPath={cutPath}
        expandedPaths={expandedPaths}
        draft={draft}
        renamingPath={renamingPath}
        onToggleExpand={toggleExpand}
        onSelectFile={handleSelect}
        onOpenFile={handleOpen}
        onTogglePath={handleToggle}
        onOpenSourcesLibrary={onOpenSourcesLibrary}
        onContextMenu={setMenu}
        onDraftSubmit={(name) => void onDraftSubmit(name)}
        onDraftCancel={() => setDraft(null)}
        onActivateDir={handleSelectDir}
      />
      {menu ? (
        <div
          ref={menuRef}
          className="fixed z-[120] min-w-[10.5rem] rounded-md border border-border bg-card py-1 shadow-lg"
          style={{
            left: Math.min(menu.x, window.innerWidth - 180),
            top: Math.min(menu.y, window.innerHeight - 280),
          }}
          role="menu"
        >
          {menuItems.map((item) =>
            item.separator ? (
              <div
                key={item.id}
                className="my-1 border-t border-border"
                role="separator"
              />
            ) : (
              <button
                key={item.id}
                type="button"
                role="menuitem"
                disabled={item.disabled}
                className={`flex w-full px-3 py-1.5 text-left text-xs disabled:cursor-not-allowed disabled:opacity-40 ${
                  item.danger
                    ? "text-destructive hover:bg-destructive/10"
                    : "text-foreground hover:bg-muted"
                }`}
                onClick={() => runMenu(item.id)}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}
