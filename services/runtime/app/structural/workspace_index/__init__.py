
"""Work 级 AST 符号索引子系统（cold/dirty/query/locate）。"""

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
