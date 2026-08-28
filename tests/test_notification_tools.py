"""Tests for notification inbox and read-state tools."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_notification_client_uses_documented_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"unreads": []}
    marked = MagicMock(status_code=200)

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_notifications(page=2, limit_bubble_ups=True) == {"unreads": []}
    with patch.object(client, "put", return_value=marked) as put:
        assert client.mark_notifications_read(["sgid-1"]) is True

    get.assert_called_once_with(
        "my/readings.json",
        params={"page": 2, "limit_bubble_ups": True},
    )
    put.assert_called_once_with("my/unreads.json", {"readables": ["sgid-1"]})


def test_bubble_ups_use_collection_pagination():
    client = BasecampClient.__new__(BasecampClient)
    with patch.object(client, "_get_paginated_collection", return_value=[{"id": "bubble-1"}]) as collect:
        assert client.get_bubble_ups() == [{"id": "bubble-1"}]
    collect.assert_called_once_with("my/readings/bubble_ups.json")


def test_subscription_client_uses_recording_routes_and_requires_a_change():
    client = BasecampClient.__new__(BasecampClient)
    get_response = MagicMock(status_code=200)
    get_response.json.return_value = {"subscribed": True, "subscribers": []}
    put_response = MagicMock(status_code=200)
    put_response.json.return_value = {"subscribed": True, "subscribers": [{"id": "2"}]}
    post_response = MagicMock(status_code=200)
    post_response.json.return_value = {"subscribed": True}
    delete_response = MagicMock(status_code=204)

    with patch.object(client, "get", return_value=get_response) as get:
        assert client.get_subscription("project-1", "recording-1")["subscribed"] is True
    with patch.object(client, "post", return_value=post_response) as post:
        assert client.subscribe_to_recording("project-1", "recording-1")["subscribed"] is True
    with patch.object(client, "delete", return_value=delete_response) as delete:
        assert client.unsubscribe_from_recording("project-1", "recording-1") is True
    with patch.object(client, "put", return_value=put_response) as put:
        assert client.update_subscription("project-1", "recording-1", ["2"], ["3"])["subscribers"]

    endpoint = "buckets/project-1/recordings/recording-1/subscription.json"
    get.assert_called_once_with(endpoint)
    post.assert_called_once_with(endpoint)
    delete.assert_called_once_with(endpoint)
    put.assert_called_once_with(endpoint, {"subscriptions": ["2"], "unsubscriptions": ["3"]})

    try:
        client.update_subscription("project-1", "recording-1")
    except ValueError as exc:
        assert "is required" in str(exc)
    else:
        raise AssertionError("empty subscription update was accepted")


def test_notification_tools_are_registered_in_both_servers():
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    expected = {
        "get_notifications", "get_bubble_ups", "mark_notifications_read",
        "get_subscription", "subscribe_to_recording", "unsubscribe_from_recording",
        "update_subscription",
    }
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_notification_tools_return_structured_results():
    client = Mock()
    client.get_notifications.return_value = {"unreads": []}
    client.get_bubble_ups.return_value = [{"id": "bubble-1"}]
    client.mark_notifications_read.return_value = True
    client.get_subscription.return_value = {"subscribed": True, "subscribers": []}
    client.subscribe_to_recording.return_value = {"subscribed": True}
    client.unsubscribe_from_recording.return_value = True
    client.update_subscription.return_value = {"subscribed": True, "subscribers": []}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_notifications(),
                await basecamp_fastmcp.get_bubble_ups(),
                await basecamp_fastmcp.mark_notifications_read(["sgid-1"]),
                await basecamp_fastmcp.get_subscription("project-1", "recording-1"),
                await basecamp_fastmcp.subscribe_to_recording("project-1", "recording-1"),
                await basecamp_fastmcp.unsubscribe_from_recording("project-1", "recording-1"),
                await basecamp_fastmcp.update_subscription("project-1", "recording-1", ["2"], ["3"]),
            )

    notifications, bubbles, marked, subscription, subscribed, unsubscribed, updated = asyncio.run(run())
    assert notifications == {"status": "success", "notifications": {"unreads": []}}
    assert bubbles == {"status": "success", "bubble_ups": [{"id": "bubble-1"}], "count": 1}
    assert marked == {"status": "success", "message": "Notifications marked as read"}
    assert subscription["subscription"]["subscribed"] is True
    assert subscribed["subscription"]["subscribed"] is True
    assert unsubscribed["message"] == "Unsubscribed from recording"
    assert updated["subscription"]["subscribed"] is True
