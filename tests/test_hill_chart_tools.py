"""Tests for Hill Chart reads and settings updates."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_hill_chart_client_uses_todoset_routes_and_project_resolution():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"enabled": True, "dots": []}

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_hill_chart("todoset-1") == {"enabled": True, "dots": []}
    get.assert_called_once_with("todosets/todoset-1/hill.json")

    client.get_project = MagicMock(
        return_value={"dock": [{"name": "todoset", "id": "todoset-1"}]}
    )
    client.get_hill_chart = MagicMock(return_value={"enabled": True})
    assert client.get_project_hill_chart("project-1") == {"enabled": True}
    client.get_hill_chart.assert_called_once_with("todoset-1")


def test_hill_chart_settings_use_documented_payload():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"enabled": True, "dots": []}
    with patch.object(client, "put", return_value=response) as put:
        assert client.update_hill_chart_settings(
            "todoset-1", ["list-1"], ["list-2"]
        )["enabled"] is True
    put.assert_called_once_with(
        "todosets/todoset-1/hills/settings.json",
        {"tracked": ["list-1"], "untracked": ["list-2"]},
    )

    try:
        client.update_hill_chart_settings("todoset-1")
    except ValueError as exc:
        assert "tracked or untracked" in str(exc)
    else:
        raise AssertionError("empty Hill Chart settings update was accepted")


def test_hill_chart_tools_are_registered_and_structured():
    expected = {"get_hill_chart", "get_project_hill_chart", "update_hill_chart_settings"}
    assert expected <= set(basecamp_fastmcp.mcp._tool_manager._tools)
    assert {tool["name"] for tool in MCPServer().tools} == set(
        basecamp_fastmcp.mcp._tool_manager._tools
    )

    client = Mock()
    client.get_project_hill_chart.return_value = {"enabled": True, "dots": []}
    client.update_hill_chart_settings.return_value = {"enabled": True}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_project_hill_chart("project-1"),
                await basecamp_fastmcp.update_hill_chart_settings(
                    "todoset-1", tracked=["list-1"]
                ),
            )

    chart, updated = asyncio.run(run())
    assert chart == {"status": "success", "hill_chart": {"enabled": True, "dots": []}}
    assert updated == {"status": "success", "hill_chart": {"enabled": True}}
