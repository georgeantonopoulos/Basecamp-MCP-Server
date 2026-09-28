"""Tests for paginated Campfire reads and line lifecycle operations."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient


def test_campfire_line_client_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    created = Mock(status_code=201)
    created.json.return_value = {"id": "line-1", "content": "Hello"}
    shown = Mock(status_code=200)
    shown.json.return_value = {"id": "line-1", "content": "Hello"}
    deleted = Mock(status_code=204)

    with patch.object(client, "post", return_value=created) as post:
        assert client.create_campfire_line("project-1", "chat-1", "Hello") == {
            "id": "line-1", "content": "Hello"
        }
    with patch.object(client, "get", return_value=shown) as get:
        assert client.get_campfire_line("project-1", "chat-1", "line-1") == {
            "id": "line-1", "content": "Hello"
        }
    with patch.object(client, "delete", return_value=deleted) as delete:
        assert client.delete_campfire_line("project-1", "chat-1", "line-1") is True

    post.assert_called_once_with(
        "buckets/project-1/chats/chat-1/lines.json",
        {"content": "Hello"},
    )
    get.assert_called_once_with(
        "buckets/project-1/chats/chat-1/lines/line-1.json"
    )
    delete.assert_called_once_with(
        "buckets/project-1/chats/chat-1/lines/line-1.json"
    )


def test_get_campfire_lines_uses_collection_pagination():
    client = BasecampClient.__new__(BasecampClient)
    with patch.object(client, "_get_paginated_collection", return_value=[{"id": "line-1"}]) as get:
        result = client.get_campfire_lines("project-1", "chat-1")

    assert result == [{"id": "line-1"}]
    get.assert_called_once_with("buckets/project-1/chats/chat-1/lines.json")


def test_get_campfires_resolves_project_chat_from_dock():
    client = BasecampClient.__new__(BasecampClient)
    client.get_project = MagicMock(
        return_value={"dock": [{"name": "chat", "id": "chat-1"}]}
    )
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "chat-1", "title": "Campfire"}

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_campfires("project-1") == [{"id": "chat-1", "title": "Campfire"}]

    get.assert_called_once_with("buckets/project-1/chats/chat-1.json")


def test_fastmcp_campfire_lifecycle_shapes():
    client = Mock()
    client.get_campfire_line.return_value = {"id": "line-1"}
    client.create_campfire_line.return_value = {"id": "line-1"}
    client.delete_campfire_line.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            shown = await basecamp_fastmcp.get_campfire_line("project-1", "chat-1", "line-1")
            created = await basecamp_fastmcp.create_campfire_line("project-1", "chat-1", "Hello")
            deleted = await basecamp_fastmcp.delete_campfire_line("project-1", "chat-1", "line-1")
        return shown, created, deleted

    shown, created, deleted = asyncio.run(run())

    assert shown == {"status": "success", "line": {"id": "line-1"}}
    assert created == {
        "status": "success",
        "line": {"id": "line-1"},
        "message": "Campfire line created successfully",
    }
    assert deleted == {
        "status": "success",
        "message": "Campfire line deleted successfully",
    }
