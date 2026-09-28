"""Tests for generic recording lifecycle actions."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_recording_status_client_uses_documented_endpoint():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=204)

    with patch.object(client, "put", return_value=response) as put:
        assert client.trash_recording("project-1", "recording-1") is True
        assert client.archive_recording("project-1", "recording-1") is True
        assert client.restore_recording("project-1", "recording-1") is True

    assert [call.args[0] for call in put.call_args_list] == [
        "buckets/project-1/recordings/recording-1/status/trashed.json",
        "buckets/project-1/recordings/recording-1/status/archived.json",
        "buckets/project-1/recordings/recording-1/status/active.json",
    ]


def test_recording_tools_are_registered_in_both_servers():
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert {"trash_recording", "archive_recording", "restore_recording"} <= fastmcp_names
    assert fastmcp_names == cli_names


def test_recording_tools_return_success_messages():
    client = Mock()
    client.trash_recording.return_value = True
    client.archive_recording.return_value = True
    client.restore_recording.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.trash_recording("project-1", "recording-1"),
                await basecamp_fastmcp.archive_recording("project-1", "recording-1"),
                await basecamp_fastmcp.restore_recording("project-1", "recording-1"),
            )

    trash, archive, restore = asyncio.run(run())
    assert trash == {"status": "success", "message": "Recording trashed successfully"}
    assert archive == {"status": "success", "message": "Recording archived successfully"}
    assert restore == {"status": "success", "message": "Recording restored successfully"}
