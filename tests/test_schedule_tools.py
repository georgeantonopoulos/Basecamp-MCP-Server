"""Tests for read-only schedule MCP coverage."""

import asyncio
from unittest.mock import Mock, patch

import basecamp_fastmcp
from mcp_server_cli import MCPServer


def test_schedule_tools_are_registered_in_both_servers():
    fastmcp_tools = basecamp_fastmcp.mcp._tool_manager._tools
    cli_tools = {tool["name"] for tool in MCPServer().tools}

    assert {"get_schedule", "get_schedule_entries"} <= set(fastmcp_tools)
    assert {"get_schedule", "get_schedule_entries"} <= cli_tools
    assert fastmcp_tools["get_schedule"].parameters["required"] == ["project_id"]
    assert fastmcp_tools["get_schedule_entries"].parameters["required"] == ["project_id"]


def test_fastmcp_schedule_tools_route_to_client():
    client = Mock()
    client.get_schedule.return_value = {"id": "schedule-1"}
    client.get_schedule_entries.return_value = [{"id": "entry-1"}]
    client.get_schedule_entry.return_value = {"id": "entry-1"}
    client.get_schedule_entry_occurrence.return_value = {"id": "occurrence-1"}
    client.create_schedule_entry.return_value = {"id": "entry-2"}
    client.update_schedule_entry.return_value = {"id": "entry-2", "summary": "Updated"}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            schedule = await basecamp_fastmcp.get_schedule("project-1")
            entries = await basecamp_fastmcp.get_schedule_entries("project-1")
            entry = await basecamp_fastmcp.get_schedule_entry("project-1", "entry-1")
            occurrence = await basecamp_fastmcp.get_schedule_entry_occurrence(
                "project-1", "entry-1", "2026-08-28"
            )
            created = await basecamp_fastmcp.create_schedule_entry(
                "project-1",
                "Planning",
                "2026-08-28T09:00:00Z",
                "2026-08-28T10:00:00Z",
                notify=True,
            )
            updated = await basecamp_fastmcp.update_schedule_entry(
                "project-1", "entry-2", summary="Updated"
            )
        return schedule, entries, entry, occurrence, created, updated

    schedule, entries, entry, occurrence, created, updated = asyncio.run(run())

    assert schedule == {"status": "success", "schedule": {"id": "schedule-1"}}
    assert entries == {
        "status": "success",
        "entries": [{"id": "entry-1"}],
        "count": 1,
    }
    assert entry == {"status": "success", "entry": {"id": "entry-1"}}
    assert occurrence == {
        "status": "success", "occurrence": {"id": "occurrence-1"}
    }
    assert created == {"status": "success", "entry": {"id": "entry-2"}}
    assert updated == {
        "status": "success", "entry": {"id": "entry-2", "summary": "Updated"}
    }
    client.get_schedule.assert_called_once_with("project-1")
    client.get_schedule_entries.assert_called_once_with("project-1")
    client.get_schedule_entry.assert_called_once_with("project-1", "entry-1")
    client.get_schedule_entry_occurrence.assert_called_once_with(
        "project-1", "entry-1", "2026-08-28"
    )
    client.create_schedule_entry.assert_called_once_with(
        "project-1",
        "Planning",
        "2026-08-28T09:00:00Z",
        "2026-08-28T10:00:00Z",
        description=None,
        participant_ids=None,
        all_day=None,
        notify=True,
    )
    client.update_schedule_entry.assert_called_once_with(
        "project-1",
        "entry-2",
        summary="Updated",
        starts_at=None,
        ends_at=None,
        description=None,
        participant_ids=None,
        all_day=None,
        notify=None,
    )


def test_update_schedule_entry_tool_rejects_empty_patch():
    result = asyncio.run(basecamp_fastmcp.update_schedule_entry("project-1", "entry-1"))
    assert result["status"] == "error"
    assert "at least one schedule entry field" in result["message"]
