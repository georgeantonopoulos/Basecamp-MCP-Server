"""Tests for Basecamp gauge reports and needle lifecycle."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_gauge_listing_uses_documented_routes_and_filters():
    client = BasecampClient.__new__(BasecampClient)
    with patch.object(client, "_get_paginated_collection", return_value=[{"id": "gauge-1"}]) as collect:
        assert client.get_gauges(["project-2", "project-1"], 20, 3) == [{"id": "gauge-1"}]
        assert client.get_gauge_needles("project-1", 10) == [{"id": "gauge-1"}]

    assert collect.call_args_list[0].args == ("reports/gauges.json",)
    assert collect.call_args_list[0].kwargs == {
        "params": {"bucket_ids": "project-2,project-1"}, "limit": 20, "page": 3
    }
    assert collect.call_args_list[1].args == ("projects/project-1/gauge/needles.json",)
    assert collect.call_args_list[1].kwargs == {"limit": 10, "page": None}


def test_gauge_mutations_use_documented_payloads():
    client = BasecampClient.__new__(BasecampClient)
    get_response = MagicMock(status_code=200)
    get_response.json.return_value = {"id": "needle-1"}
    created_response = MagicMock(status_code=201)
    created_response.json.return_value = {"id": "needle-1", "position": 50}
    updated_response = MagicMock(status_code=200)
    updated_response.json.return_value = {"id": "needle-1", "description": "Done"}
    deleted_response = MagicMock(status_code=204)
    toggled_response = MagicMock(status_code=200)

    with patch.object(client, "get", return_value=get_response) as get:
        assert client.get_gauge_needle("needle-1") == {"id": "needle-1"}
    with patch.object(client, "post", return_value=created_response) as post:
        assert client.create_gauge_needle(
            "project-1", 50, "yellow", "Halfway", "custom", ["person-1"]
        )["position"] == 50
    with patch.object(client, "put", side_effect=[updated_response, toggled_response]) as put:
        assert client.update_gauge_needle("needle-1", "Done")["description"] == "Done"
        assert client.toggle_gauge("project-1", False) is True
    with patch.object(client, "delete", return_value=deleted_response) as delete:
        assert client.delete_gauge_needle("needle-1") is True

    get.assert_called_once_with("gauge_needles/needle-1.json")
    post.assert_called_once_with(
        "projects/project-1/gauge/needles.json",
        {
            "gauge_needle": {"position": 50, "color": "yellow", "description": "Halfway"},
            "notify": "custom",
            "subscriptions": ["person-1"],
        },
    )
    assert put.call_args_list[0].args == (
        "gauge_needles/needle-1.json", {"gauge_needle": {"description": "Done"}}
    )
    assert put.call_args_list[1].args == (
        "projects/project-1/gauge.json", {"gauge": {"enabled": False}}
    )
    delete.assert_called_once_with("gauge_needles/needle-1.json")


def test_gauge_mutations_reject_invalid_values():
    client = BasecampClient.__new__(BasecampClient)
    for call in (
        lambda: client.create_gauge_needle("project-1", 101),
        lambda: client.create_gauge_needle("project-1", 50, "purple"),
        lambda: client.create_gauge_needle("project-1", 50, notify="custom"),
        lambda: client.update_gauge_needle("needle-1", None),
        lambda: client.toggle_gauge("project-1", "false"),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid gauge mutation was accepted")


def test_gauge_tools_are_registered_in_both_servers():
    expected = {
        "get_gauges", "get_gauge_needles", "get_gauge_needle", "create_gauge_needle",
        "update_gauge_needle", "delete_gauge_needle", "toggle_gauge",
    }
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_gauge_wrappers_return_structured_results():
    client = Mock()
    client.get_gauges.return_value = [{"id": "gauge-1"}]
    client.create_gauge_needle.return_value = {"id": "needle-1"}
    client.toggle_gauge.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_gauges(["project-1"]),
                await basecamp_fastmcp.create_gauge_needle("project-1", 80),
                await basecamp_fastmcp.toggle_gauge("project-1", True),
            )

    gauges, needle, toggled = asyncio.run(run())
    assert gauges == {"status": "success", "gauges": [{"id": "gauge-1"}], "count": 1}
    assert needle == {
        "status": "success", "needle": {"id": "needle-1"}, "message": "Gauge needle created"
    }
    assert toggled == {"status": "success", "message": "Gauge enabled"}
