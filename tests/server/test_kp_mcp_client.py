from unittest.mock import AsyncMock, MagicMock

import pytest

from src.server.ai.kp_mcp_client import KpMcpClient


@pytest.mark.asyncio
async def test_kp_mcp_client_close_closes_streamable_http_exit_stack():
    client = KpMcpClient()
    exit_stack = MagicMock()
    exit_stack.aclose = AsyncMock()
    client._exit_stack = exit_stack
    client._read_stream = object()
    client._write_stream = object()

    await client.close()

    exit_stack.aclose.assert_awaited_once_with()
    assert client._exit_stack is None
    assert client._read_stream is None
    assert client._write_stream is None
