/** Settings inspect APIs (RAG chunks · AST outline). */

import { API_BASE, apiAuthHeaders } from "../shared/api/client";

const sessionFetchInit = { credentials: "include" as RequestCredentials };

export type ChunkFileRow = {
  path: string;
  visibility: string;
  chunk_count: number;
  line_start?: number | null;
  line_end?: number | null;
};

export type SourceChunk = {
  chunk_id: string;
  path: string;
  visibility: string;
  section_title: string;
  citation_id: string;
  line_start?: number | null;
  line_end?: number | null;
  text: string;
  chars: number;
  truncated?: boolean;
};

export type ChunkFilesResponse = {
  backend?: string;
  visibility?: string;
  files: ChunkFileRow[];
  total: number;
  truncated?: boolean;
};

export type ChunksForPathResponse = {
  backend?: string;
  path: string;
  chunks: SourceChunk[];
  total: number;
  truncated?: boolean;
};

export type AstInspectFileRow = {
  path: string;
  lang: string;
  size: number;
  generation: number;
  symbol_count: number;
  import_count?: number;
};

export type AstSymbolNode = {
  name: string;
  kind: string;
  line: number;
  col?: number;
  end_line?: number | null;
  container?: string | null;
  children?: AstSymbolNode[];
};

export type AstInspectFile = {
  path: string;
  lang?: string;
  size?: number;
  missing?: boolean;
  imports?: string[];
  symbols?: Array<{
    name: string;
    kind: string;
    line: number;
    col?: number;
    end_line?: number | null;
    container?: string | null;
  }>;
  tree?: AstSymbolNode[];
  tree_text?: string;
};

export type AstInspectResponse = {
  enabled?: boolean;
  status?: string;
  generation?: number;
  files: AstInspectFileRow[];
  total?: number;
  truncated?: boolean;
  file?: AstInspectFile | null;
};

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, {
    ...sessionFetchInit,
    headers: apiAuthHeaders(),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status} ${detail}`.trim());
  }
  return res.json() as Promise<T>;
}

export async function fetchSourceChunkFiles(opts?: {
  workId?: string;
  visibility?: "all" | "seed" | "private";
  q?: string;
  limit?: number;
}): Promise<ChunkFilesResponse> {
  const params = new URLSearchParams();
  if (opts?.workId) params.set("work_id", opts.workId);
  if (opts?.visibility) params.set("visibility", opts.visibility);
  if (opts?.q) params.set("q", opts.q);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return getJson(
    `${API_BASE}/admin/workspace/sources/chunks${qs ? `?${qs}` : ""}`,
  );
}

export async function fetchSourceChunksForPath(
  path: string,
  opts?: { workId?: string; limit?: number },
): Promise<ChunksForPathResponse> {
  const params = new URLSearchParams();
  params.set("path", path);
  if (opts?.workId) params.set("work_id", opts.workId);
  if (opts?.limit) params.set("limit", String(opts.limit));
  return getJson(
    `${API_BASE}/admin/workspace/sources/chunks?${params.toString()}`,
  );
}

export async function fetchAstIndexInspect(opts?: {
  workId?: string;
  path?: string;
  q?: string;
  limit?: number;
}): Promise<AstInspectResponse> {
  const params = new URLSearchParams();
  if (opts?.workId) params.set("work_id", opts.workId);
  if (opts?.path) params.set("path", opts.path);
  if (opts?.q) params.set("q", opts.q);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return getJson(
    `${API_BASE}/admin/workspace/ast-index/inspect${qs ? `?${qs}` : ""}`,
  );
}
