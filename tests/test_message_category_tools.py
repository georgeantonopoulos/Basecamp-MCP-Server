"""Tests for message type/category management."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_message_category_client_uses_documented_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "category-1", "name": "Announcement"}
    created = MagicMock(status_code=201)
    created.json.return_value = {"id": "category-1"}
    deleted = MagicMock(status_code=204)

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_message_category("project-1", "category-1") == {
            "id": "category-1", "name": "Announcement"
        }
    with patch.object(client, "post", return_value=created) as post:
        assert client.create_message_category("project-1", "Announcement", "📢") == {"id": "category-1"}
    with patch.object(client, "put", return_value=response) as put:
        assert client.update_message_category("project-1", "category-1", "Update", "📝") == {
            "id": "category-1", "name": "Announcement"
        }
    with patch.object(client, "delete", return_value=deleted) as delete:
        assert client.delete_message_category("project-1", "category-1") is True

    get.assert_called_once_with("buckets/project-1/categories/category-1.json")
    post.assert_called_once_with(
        "buckets/project-1/categories.json", {"name": "Announcement", "icon": "📢"}
    )
    put.assert_called_once_with(
        "buckets/project-1/categories/category-1.json", {"name": "Update", "icon": "📝"}
    )
    delete.assert_called_once_with("buckets/project-1/categories/category-1.json")


def test_message_category_tools_are_registered_in_both_servers():
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    expected = {
        "get_message_category", "create_message_category",
        "update_message_category", "delete_message_category",
    }
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_message_category_wrappers_return_structured_results():
    client = Mock()
    client.get_message_category.return_value = {"id": "category-1"}
    client.create_message_category.return_value = {"id": "category-1"}
    client.update_message_category.return_value = {"id": "category-1"}
    client.delete_message_category.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_message_category("project-1", "category-1"),
                await basecamp_fastmcp.create_message_category("project-1", "Announcement", "📢"),
                await basecamp_fastmcp.update_message_category("project-1", "category-1", "Update", "📝"),
                await basecamp_fastmcp.delete_message_category("project-1", "category-1"),
            )

    shown, created, updated, deleted = asyncio.run(run())
    assert shown == {"status": "success", "category": {"id": "category-1"}}
    assert created["category"] == {"id": "category-1"}
    assert updated["category"] == {"id": "category-1"}
    assert deleted == {"status": "success", "message": "Message category deleted successfully"}
