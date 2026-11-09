"""Tests for project dock-tool management."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_dock_client_uses_documented_routes_and_payloads():
    client = BasecampClient.__new__(BasecampClient)
    detail = MagicMock(status_code=200)
    detail.json.return_value = {"id": "tool-1", "title": "Chat"}
    created = MagicMock(status_code=201)
    created.json.return_value = {"id": "tool-2"}
    renamed = MagicMock(status_code=200)
    renamed.json.return_value = {"id": "tool-1", "title": "Team Chat"}
    success_200 = MagicMock(status_code=200)
    success_201 = MagicMock(status_code=201)
    success_204 = MagicMock(status_code=204)

    with patch.object(client, "get", return_value=detail) as get:
        assert client.get_dock_tool("tool-1")["title"] == "Chat"
    with patch.object(client, "post", side_effect=[created, success_201]) as post:
        assert client.create_dock_tool(
            "project-1", "Chat::Transcript", "Team Chat", True
        )["id"] == "tool-2"
        assert client.enable_dock_tool("project-1", "tool-1") is True
    with patch.object(client, "put", side_effect=[renamed, success_200]) as put:
        assert client.update_dock_tool("tool-1", "Team Chat")["title"] == "Team Chat"
        assert client.reposition_dock_tool("project-1", "tool-1", 2) is True
    with patch.object(client, "delete", side_effect=[success_204, success_204]) as delete:
        assert client.disable_dock_tool("project-1", "tool-1") is True
        assert client.trash_dock_tool("tool-1") is True

    get.assert_called_once_with("dock/tools/tool-1.json")
    post.assert_any_call(
        "buckets/project-1/dock/tools.json",
        {"tool_type": "Chat::Transcript", "title": "Team Chat", "visible_to_clients": True},
    )
    post.assert_any_call("buckets/project-1/recordings/tool-1/position.json")
    put.assert_any_call("dock/tools/tool-1.json", {"title": "Team Chat"})
    put.assert_any_call(
        "buckets/project-1/recordings/tool-1/position.json", {"position": 2}
    )
    delete.assert_any_call("buckets/project-1/recordings/tool-1/position.json")
    delete.assert_any_call("dock/tools/tool-1.json")


def test_dock_client_validates_inputs():
    client = BasecampClient.__new__(BasecampClient)
    for call in (
        lambda: client.create_dock_tool("project-1", "Unknown"),
        lambda: client.create_dock_tool("project-1", "Vault", visible_to_clients="yes"),
        lambda: client.update_dock_tool("tool-1", ""),
        lambda: client.reposition_dock_tool("project-1", "tool-1", 0),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid dock operation was accepted")


def test_dock_tools_are_registered_and_structured():
    expected = {
        "get_dock_tool", "create_dock_tool", "update_dock_tool", "enable_dock_tool",
        "reposition_dock_tool", "disable_dock_tool", "trash_dock_tool",
    }
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names

    client = Mock()
    client.get_dock_tool.return_value = {"id": "tool-1"}
    client.trash_dock_tool.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_dock_tool("tool-1"),
                await basecamp_fastmcp.trash_dock_tool("tool-1"),
            )

    detail, deleted = asyncio.run(run())
    assert detail == {"status": "success", "tool": {"id": "tool-1"}}
    assert deleted == {"status": "success", "message": "Dock tool permanently deleted"}
