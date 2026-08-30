"""Tests for Basecamp timesheet reporting and CRUD."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_timesheet_report_uses_documented_filters():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = [{"id": "entry-1"}]

    with patch.object(client, "get", return_value=response) as get:
        assert client.get_timesheet_report(
            "2026-08-01", "2026-08-28", "person-1", "project-1"
        ) == [{"id": "entry-1"}]

    get.assert_called_once_with(
        "reports/timesheet.json",
        params={
            "start_date": "2026-08-01",
            "end_date": "2026-08-28",
            "person_id": "person-1",
            "bucket_id": "project-1",
        },
    )


def test_timesheet_report_requires_both_dates():
    client = BasecampClient.__new__(BasecampClient)
    try:
        client.get_timesheet_report(start_date="2026-08-01")
    except ValueError as exc:
        assert "provided together" in str(exc)
    else:
        raise AssertionError("partial timesheet date range was accepted")


def test_timesheet_collection_routes_use_pagination_helper():
    client = BasecampClient.__new__(BasecampClient)
    with patch.object(client, "_get_paginated_collection", return_value=[{"id": "e"}]) as collect:
        assert client.get_project_timesheet("project-1", 25, 2) == [{"id": "e"}]
        assert client.get_recording_timesheet("recording-1", 10) == [{"id": "e"}]

    assert collect.call_args_list[0].args == ("projects/project-1/timesheet.json",)
    assert collect.call_args_list[0].kwargs == {"limit": 25, "page": 2}
    assert collect.call_args_list[1].args == ("recordings/recording-1/timesheet.json",)
    assert collect.call_args_list[1].kwargs == {"limit": 10, "page": None}


def test_timesheet_entry_client_uses_canonical_flat_routes_and_payloads():
    client = BasecampClient.__new__(BasecampClient)
    get_response = MagicMock(status_code=200)
    get_response.json.return_value = {"id": "entry-1"}
    created_response = MagicMock(status_code=201)
    created_response.json.return_value = {"id": "entry-1", "hours": "1:30"}
    updated_response = MagicMock(status_code=200)
    updated_response.json.return_value = {"id": "entry-1", "hours": "2.5"}
    deleted_response = MagicMock(status_code=204)

    with patch.object(client, "get", return_value=get_response) as get:
        assert client.get_timesheet_entry("entry-1") == {"id": "entry-1"}
    with patch.object(client, "post", return_value=created_response) as post:
        assert client.create_timesheet_entry(
            "recording-1", "2026-08-28", "1:30", "Prep", "person-1"
        )["hours"] == "1:30"
    with patch.object(client, "put", return_value=updated_response) as put:
        assert client.update_timesheet_entry("entry-1", hours="2.5")["hours"] == "2.5"
    with patch.object(client, "delete", return_value=deleted_response) as delete:
        assert client.delete_timesheet_entry("entry-1") is True

    get.assert_called_once_with("timesheet_entries/entry-1.json")
    post.assert_called_once_with(
        "recordings/recording-1/timesheet/entries.json",
        {
            "date": "2026-08-28",
            "hours": "1:30",
            "description": "Prep",
            "person_id": "person-1",
        },
    )
    put.assert_called_once_with(
        "timesheet_entries/entry-1.json", {"hours": "2.5"}
    )
    delete.assert_called_once_with("timesheet_entries/entry-1.json")


def test_timesheet_mutations_validate_required_fields():
    client = BasecampClient.__new__(BasecampClient)
    for call in (
        lambda: client.create_timesheet_entry("recording-1", "", "1.0"),
        lambda: client.create_timesheet_entry("recording-1", "2026-08-28", ""),
        lambda: client.update_timesheet_entry("entry-1"),
    ):
        try:
            call()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid timesheet mutation was accepted")


def test_timesheet_tools_are_registered_in_both_servers():
    expected = {
        "get_timesheet_report",
        "get_project_timesheet",
        "get_recording_timesheet",
        "get_timesheet_entry",
        "create_timesheet_entry",
        "update_timesheet_entry",
        "delete_timesheet_entry",
    }
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_timesheet_wrappers_return_structured_results_and_validate_input():
    client = Mock()
    client.get_timesheet_report.return_value = [{"id": "entry-1"}]
    client.get_project_timesheet.return_value = [{"id": "entry-2"}]
    client.create_timesheet_entry.return_value = {"id": "entry-3"}
    client.delete_timesheet_entry.return_value = True

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_timesheet_report("2026-08-01", "2026-08-28"),
                await basecamp_fastmcp.get_project_timesheet("project-1"),
                await basecamp_fastmcp.create_timesheet_entry(
                    "recording-1", "2026-08-28", "1.5"
                ),
                await basecamp_fastmcp.delete_timesheet_entry("entry-3"),
            )

    report, project, created, deleted = asyncio.run(run())
    assert report == {"status": "success", "entries": [{"id": "entry-1"}], "count": 1}
    assert project == {"status": "success", "entries": [{"id": "entry-2"}], "count": 1}
    assert created == {
        "status": "success", "entry": {"id": "entry-3"}, "message": "Timesheet entry created"
    }
    assert deleted == {"status": "success", "message": "Timesheet entry deleted"}

    invalid = asyncio.run(basecamp_fastmcp.get_timesheet_report(start_date="2026-08-01"))
    assert invalid == {
        "status": "error",
        "error": "Invalid input",
        "message": "start_date and end_date must be provided together",
    }
