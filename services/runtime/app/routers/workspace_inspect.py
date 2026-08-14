"""Internal inspect routes for Settings (RAG chunks · AST outline)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Query


def register_inspect_routes(router, *, verify_internal_token, tenant_query) -> None:
    @router.get("/sources/chunks")
    async def workspace_sources_chunks(
        path: str | None = None,
        visibility: str | None = Query(default="all"),
        q: str | None = None,
        limit: int = Query(default=200, ge=1, le=400),
        work_id: str | None = None,
        work_root: str | None = None,
        owner_user_id: str | None = None,
        visibility_seed: str | None = None,
        _: None = Depends(verify_internal_token),
    ):
        from app.retrieval.inspect_chunks import (
            inspect_chunk_files,
            inspect_chunks_for_path,
        )
        from app.services.workspace_scope import workspace_tenant_scope

        with workspace_tenant_scope(
            **tenant_query(work_id, work_root, owner_user_id, visibility_seed)
        ):
            if path:
                return inspect_chunks_for_path(path, limit=min(int(limit), 120))
            return inspect_chunk_files(visibility=visibility, q=q, limit=limit)

    @router.get("/ast-index/inspect")
    async def workspace_ast_index_inspect(
        path: str | None = None,
        q: str | None = None,
        limit: int = Query(default=200, ge=1, le=400),
        work_id: str | None = None,
        work_root: str | None = None,
        owner_user_id: str | None = None,
        visibility_seed: str | None = None,
        _: None = Depends(verify_internal_token),
    ):
        from uuid import UUID

        from app.services.workspace_scope import workspace_tenant_scope
        from app.structural.workspace_index.inspect import inspect_ast_index
        from app.tenant_context import current_work_root_path

        if not work_id or not owner_user_id:
            raise HTTPException(status_code=400, detail="work_id and owner_user_id required")
        try:
            UUID(work_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid work_id") from exc

        with workspace_tenant_scope(
            **tenant_query(work_id, work_root, owner_user_id, visibility_seed)
        ):
            return await inspect_ast_index(
                work_id=work_id,
                owner_user_id=owner_user_id,
                work_root=current_work_root_path(),
                path=path,
                q=q,
                limit=limit,
            )
