"""Tests for complete webhook CRUD and URL validation."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_webhook_client_lists_and_reads_with_documented_routes():
    client = BasecampClient.__new__(BasecampClient)
    listing = [{"id": "hook-1"}]
    with patch.object(client, "_get_paginated_collection", return_value=listing) as collect:
        assert client.get_webhooks("project-1") == listing
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "hook-1", "recent_deliveries": []}
    with patch.object(client, "get", return_value=response) as get:
        assert client.get_webhook("project-1", "hook-1")["id"] == "hook-1"

    collect.assert_called_once_with("buckets/project-1/webhooks.json")
    get.assert_called_once_with("buckets/project-1/webhooks/hook-1.json")


def test_webhook_client_validates_https_and_updates_payload():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "hook-1", "active": True}
    with patch.object(client, "put", return_value=response) as put:
        assert client.update_webhook(
            "project-1", "hook-1", "https://example.test/hook", ["Todo"], True
        )["active"] is True
    put.assert_called_once_with(
        "buckets/project-1/webhooks/hook-1.json",
        {"payload_url": "https://example.test/hook", "types": ["Todo"], "active": True},
    )

    try:
        client.update_webhook("project-1", "hook-1", "http://example.test/hook")
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("insecure webhook URL was accepted")


def test_webhook_tools_are_registered_and_return_structured_results():
    names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert {"get_webhook", "update_webhook"} <= names
    assert names == cli_names

    client = Mock()
    client.get_webhook.return_value = {"id": "hook-1"}
    client.update_webhook.return_value = {"id": "hook-1", "active": True}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_webhook("project-1", "hook-1"),
                await basecamp_fastmcp.update_webhook(
                    "project-1", "hook-1", "https://example.test/hook", active=True
                ),
            )

    got, updated = asyncio.run(run())
    assert got == {"status": "success", "webhook": {"id": "hook-1"}}
    assert updated == {
        "status": "success", "webhook": {"id": "hook-1", "active": True}
    }
