"""Tests for project lifecycle and people/access coverage."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_project_lifecycle_client_uses_documented_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    created = MagicMock(status_code=201)
    created.json.return_value = {"id": "project-1"}
    updated = MagicMock(status_code=200)
    updated.json.return_value = {"id": "project-1", "name": "Updated"}
    deleted = MagicMock(status_code=204)

    with patch.object(client, "post", return_value=created) as post:
        assert client.create_project("New", "Description", "team") == {"id": "project-1"}
    with patch.object(client, "put", return_value=updated) as put:
        assert client.update_project("project-1", "Updated", "Description", "team", "2026-01-01", "2026-02-01") == {
            "id": "project-1", "name": "Updated"
        }
    with patch.object(client, "delete", return_value=deleted) as delete:
        assert client.trash_project("project-1") is True

    post.assert_called_once_with(
        "projects.json", {"name": "New", "description": "Description", "admissions": "team"}
    )
    put.assert_called_once_with(
        "projects/project-1.json",
        {
            "name": "Updated",
            "description": "Description",
            "admissions": "team",
            "schedule_attributes": {"start_date": "2026-01-01", "end_date": "2026-02-01"},
        },
    )
    delete.assert_called_once_with("projects/project-1.json")


def test_people_client_uses_project_and_profile_endpoints():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"people": [{"id": "person-1"}]}

    with patch.object(
        client,
        "_get_paginated_collection",
        return_value=[{"id": "person-1"}, {"id": "person-2"}],
    ) as collect:
        assert client.get_project_people("project-1") == [
            {"id": "person-1"},
            {"id": "person-2"},
        ]
    with patch.object(client, "get", return_value=response) as get:
        assert client.get_pingable_people() == {"people": [{"id": "person-1"}]}
        assert client.get_person("person-1") == {"people": [{"id": "person-1"}]}
        assert client.get_my_profile() == {"people": [{"id": "person-1"}]}

    collect.assert_called_once_with("projects/project-1/people.json")
    assert [call.args[0] for call in get.call_args_list] == [
        "circles/people.json",
        "people/person-1.json",
        "my/profile.json",
    ]


def test_update_project_people_sends_only_requested_operations():
    client = BasecampClient.__new__(BasecampClient)
    response = MagicMock(status_code=200)
    response.json.return_value = {"granted": [{"id": "person-1"}]}

    with patch.object(client, "put", return_value=response) as put:
        result = client.update_project_people("project-1", grant=["person-1"], revoke=["person-2"])

    assert result == {"granted": [{"id": "person-1"}]}
    put.assert_called_once_with(
        "projects/project-1/people/users.json",
        {"grant": ["person-1"], "revoke": ["person-2"]},
    )


def test_project_and_people_tools_are_registered_in_both_servers():
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    expected = {
        "create_project", "update_project", "trash_project", "get_project_people",
        "update_project_people", "get_pingable_people", "get_person", "get_my_profile",
    }
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_project_and_people_wrappers_return_structured_results():
    client = Mock()
    client.create_project.return_value = {"id": "project-1"}
    client.update_project.return_value = {"id": "project-1"}
    client.trash_project.return_value = True
    client.get_project_people.return_value = [{"id": "person-1"}]
    client.update_project_people.return_value = {"granted": [{"id": "person-1"}]}
    client.get_pingable_people.return_value = [{"id": "person-1"}]
    client.get_person.return_value = {"id": "person-1"}
    client.get_my_profile.return_value = {"id": "person-1"}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.create_project("New"),
                await basecamp_fastmcp.update_project("project-1", "Updated"),
                await basecamp_fastmcp.trash_project("project-1"),
                await basecamp_fastmcp.get_project_people("project-1"),
                await basecamp_fastmcp.update_project_people("project-1", grant=["person-1"]),
                await basecamp_fastmcp.get_pingable_people(),
                await basecamp_fastmcp.get_person("person-1"),
                await basecamp_fastmcp.get_my_profile(),
            )

    results = asyncio.run(run())
    assert results[0]["project"] == {"id": "project-1"}
    assert results[1]["project"] == {"id": "project-1"}
    assert results[2]["status"] == "success"
    assert results[3] == {"status": "success", "people": [{"id": "person-1"}], "count": 1}
    assert results[4]["result"] == {"granted": [{"id": "person-1"}]}
    assert results[5]["people"] == [{"id": "person-1"}]
    assert results[6]["person"] == {"id": "person-1"}
    assert results[7]["person"] == {"id": "person-1"}
