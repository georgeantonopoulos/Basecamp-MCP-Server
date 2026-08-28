"""Tests for native Basecamp full-text search."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_native_search_client_uses_documented_filters():
    client = BasecampClient.__new__(BasecampClient)
    client._get_paginated_collection = MagicMock(return_value=[{"id": "recording-1"}])

    result = client.search_recordings(
        "launch",
        type_names=["Message", "Todo"],
        bucket_ids=["project-1"],
        creator_ids=["person-1"],
        file_type="PDF",
        exclude_chat=True,
        since="last_30_days",
        sort="recency",
        per_page=25,
    )

    assert result == [{"id": "recording-1"}]
    client._get_paginated_collection.assert_called_once_with(
        "search.json",
        params={
            "q": "launch",
            "type_names[]": ["Message", "Todo"],
            "bucket_ids[]": ["project-1"],
            "creator_ids[]": ["person-1"],
            "file_type": "PDF",
            "exclude_chat": 1,
            "since": "last_30_days",
            "sort": "recency",
            "per_page": 25,
        },
    )


def test_search_metadata_uses_documented_endpoint():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"recording_search_types": []}

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_search_metadata() == {"recording_search_types": []}

    get.assert_called_once_with("searches/metadata.json")


def test_native_search_tools_are_registered_in_both_servers():
    fastmcp_names = {
        tool.name for tool in asyncio.run(basecamp_fastmcp.mcp.list_tools())
    }
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert {"get_search_metadata", "search_recordings"} <= fastmcp_names
    assert fastmcp_names == cli_names


def test_native_search_tools_return_structured_results():
    client = Mock()
    client.get_search_metadata.return_value = {"recording_search_types": []}
    client.search_recordings.return_value = [{"id": "recording-1"}]

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_search_metadata(),
                await basecamp_fastmcp.search_recordings("launch", exclude_chat=True),
            )

    metadata, results = asyncio.run(run())
    assert metadata == {"status": "success", "metadata": {"recording_search_types": []}}
    assert results == {
        "status": "success",
        "query": "launch",
        "results": [{"id": "recording-1"}],
        "count": 1,
    }
