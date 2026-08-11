"""Agent workspace async AST index (docs/plan/agent-workspace-ast-index.md).

Per-work_id symbol/boundary table — no vectors, no RAG. Memory projection is
the only query surface; Postgres is a restart snapshot. Locate consumers weld
into search_codebase (A3); this package owns store / projection / cold-start.
"""

from __future__ import annotations

from app.structural.workspace_index.projection import (
    IndexProjection,
    ProjectionRegistry,
    get_projection_registry,
)
from app.structural.workspace_index.service import (
    AstIndexService,
    get_ast_index_service,
)
from app.structural.workspace_index.types import (
    FileEntry,
    IndexMeta,
    IndexStatus,
    SymbolHit,
    SymbolRec,
)

__all__ = [
    "AstIndexService",
    "FileEntry",
    "IndexMeta",
    "IndexProjection",
    "IndexStatus",
    "ProjectionRegistry",
    "SymbolHit",
    "SymbolRec",
    "get_ast_index_service",
    "get_projection_registry",
]
