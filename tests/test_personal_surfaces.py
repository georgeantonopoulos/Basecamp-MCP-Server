"""Tests for current-user bookmarks, drafts, notes, and calendar surfaces."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_personal_collection_clients_use_documented_endpoints_and_limits():
    client = BasecampClient.__new__(BasecampClient)
    bookmarks = [{"id": "bookmark-1"}]
    drafts = [{"id": "draft-1"}]

    with patch.object(client, "_get_paginated_collection", side_effect=[bookmarks, drafts]) as fetch:
        assert client.get_my_bookmarks(5) == bookmarks
        assert client.get_my_drafts(5) == drafts

    assert fetch.call_args_list[0].args == ("my/bookmarks.json",)
    assert fetch.call_args_list[0].kwargs == {"limit": 5}
    assert fetch.call_args_list[1].args == ("my/drafts.json",)
    assert fetch.call_args_list[1].kwargs == {"limit": 5}


def test_personal_collection_clients_reject_non_positive_limits():
    client = BasecampClient.__new__(BasecampClient)
    for method in (client.get_my_bookmarks, client.get_my_drafts):
        try:
            method(0)
        except ValueError as exc:
            assert "limit must be >= 1" in str(exc)
        else:
            raise AssertionError("invalid collection limit was accepted")


def test_bookmark_lifecycle_uses_recording_routes():
    client = BasecampClient.__new__(BasecampClient)
    get_response = MagicMock(status_code=200)
    get_response.json.return_value = {"bookmarked": True}
    create_response = MagicMock(status_code=201)
    delete_response = MagicMock(status_code=204)

    with patch.object(client, "get", return_value=get_response) as get:
        assert client.get_bookmark_status("recording-1") == {"bookmarked": True}
    with patch.object(client, "post", return_value=create_response) as post:
        assert client.create_bookmark("recording-1") is True
    with patch.object(client, "delete", return_value=delete_response) as delete:
        assert client.delete_bookmark("recording-1") is True

    get.assert_called_once_with("recordings/recording-1/bookmark.json")
    post.assert_called_once_with("recordings/recording-1/bookmark.json")
    delete.assert_called_once_with("recordings/recording-1/bookmark.json")


def test_note_and_calendar_clients_use_documented_payloads():
    client = BasecampClient.__new__(BasecampClient)
    get_response = MagicMock(status_code=200)
    get_response.json.side_effect = [{"content": "old"}, {"id": "cal-1"}]
    put_response = MagicMock(status_code=200)
    put_response.json.side_effect = [{"content": "new"}, {"id": "cal-1", "color": "blue"}]

    with patch.object(client, "get", return_value=get_response) as get:
        assert client.get_my_note() == {"content": "old"}
        assert client.get_calendar("cal-1") == {"id": "cal-1"}
    with patch.object(client, "put", return_value=put_response) as put:
        assert client.update_my_note("new") == {"content": "new"}
        assert client.update_calendar("cal-1", "blue") == {"id": "cal-1", "color": "blue"}

    assert get.call_args_list[0].args == ("my/notes.json",)
    assert get.call_args_list[1].args == ("calendars/cal-1.json",)
    assert put.call_args_list[0].args == ("my/notes.json", {"note": {"content": "new"}})
    assert put.call_args_list[1].args == ("calendars/cal-1.json", {"calendar": {"color": "blue"}})


def test_calendar_client_rejects_unknown_color():
    client = BasecampClient.__new__(BasecampClient)
    try:
        client.update_calendar("cal-1", "chartreuse")
    except ValueError as exc:
        assert "color must be one of" in str(exc)
    else:
        raise AssertionError("invalid calendar color was accepted")


def test_personal_surface_tools_are_registered_in_both_servers():
    expected = {
        "get_my_bookmarks", "get_bookmark_status", "create_bookmark", "delete_bookmark",
        "get_my_drafts", "get_my_note", "update_my_note", "get_calendar", "update_calendar",
    }
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_personal_surface_tools_return_structured_results():
    client = Mock()
    client.get_my_bookmarks.return_value = [{"id": "bookmark-1"}]
    client.get_bookmark_status.return_value = {"bookmarked": True}
    client.create_bookmark.return_value = True
    client.delete_bookmark.return_value = True
    client.get_my_drafts.return_value = [{"id": "draft-1"}]
    client.get_my_note.return_value = {"content": "old"}
    client.update_my_note.return_value = {"content": "new"}
    client.get_calendar.return_value = {"id": "cal-1"}
    client.update_calendar.return_value = {"id": "cal-1", "color": "blue"}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return await basecamp_fastmcp.get_my_bookmarks(5), await basecamp_fastmcp.get_bookmark_status("recording-1"), await basecamp_fastmcp.create_bookmark("recording-1"), await basecamp_fastmcp.delete_bookmark("recording-1"), await basecamp_fastmcp.get_my_drafts(5), await basecamp_fastmcp.get_my_note(), await basecamp_fastmcp.update_my_note("new"), await basecamp_fastmcp.get_calendar("cal-1"), await basecamp_fastmcp.update_calendar("cal-1", "blue")

    results = asyncio.run(run())
    assert results[0]["count"] == 1
    assert results[1]["bookmark"] == {"bookmarked": True}
    assert results[2]["message"] == "Recording bookmarked"
    assert results[3]["message"] == "Bookmark removed"
    assert results[4]["drafts"] == [{"id": "draft-1"}]
    assert results[5]["note"] == {"content": "old"}
    assert results[6]["note"] == {"content": "new"}
    assert results[7]["calendar"] == {"id": "cal-1"}
    assert results[8]["calendar"]["color"] == "blue"
