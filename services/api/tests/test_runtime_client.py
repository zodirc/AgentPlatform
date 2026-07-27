from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.context import set_request_id
from app.middleware.request_context import REQUEST_ID_HEADER
from app.services.command import runtime_client as runtime_client_mod
from app.services.command.runtime_client import RuntimeClient


@pytest.mark.asyncio
async def test_runtime_client_propagates_request_id() -> None:
    request_id = UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
    set_request_id(request_id)
    client = RuntimeClient(base_url="http://runtime:8001")
    same_runtime_client = RuntimeClient(base_url="http://runtime:8001")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=mock_response)

    runtime_client_mod._clients.clear()
    with patch(
        "app.services.command.runtime_client.httpx.AsyncClient", return_value=mock_http
    ) as factory:
        await client.sync_sources_index()
        await same_runtime_client.sync_sources_index()

    headers = mock_http.post.await_args.kwargs["headers"]
    assert headers[REQUEST_ID_HEADER] == str(request_id)
    assert "X-Internal-Token" in headers
    assert mock_http.post.await_args.args[0] == "/internal/commands/sync-sources-index"
    factory.assert_called_once()
    runtime_client_mod._clients.clear()
