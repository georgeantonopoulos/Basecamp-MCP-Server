"""Tests for project template and construction coverage."""

import asyncio
from unittest.mock import MagicMock, Mock, patch

import basecamp_fastmcp
from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def test_template_client_uses_documented_endpoints_and_pagination():
    client = BasecampClient.__new__(BasecampClient)
    client._get_paginated_collection = MagicMock(return_value=[{"id": "template-1"}])
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "template-1", "name": "Starter"}
    created = MagicMock(status_code=201)
    created.json.return_value = {"id": "template-1"}
    deleted = MagicMock(status_code=204)

    assert client.get_templates("archived") == [{"id": "template-1"}]
    client._get_paginated_collection.assert_called_once_with(
        "templates.json", params={"status": "archived"}
    )
    with patch.object(client, "get", return_value=response) as get:
        assert client.get_template("template-1") == {"id": "template-1", "name": "Starter"}
    get.assert_called_once_with("templates/template-1.json")
    with patch.object(client, "post", return_value=created) as post:
        assert client.create_template("Starter", "Description") == {"id": "template-1"}
        assert client.create_project_from_template("template-1", "New", "Desc") == {"id": "template-1"}
    assert post.call_args_list[0].args == ("templates.json", {"name": "Starter", "description": "Description"})
    assert post.call_args_list[1].args == (
        "templates/template-1/project_constructions.json",
        {"project": {"name": "New", "description": "Desc"}},
    )
    with patch.object(client, "delete", return_value=deleted) as delete:
        assert client.trash_template("template-1") is True
    delete.assert_called_once_with("templates/template-1.json")


def test_template_update_fetches_name_for_description_only_changes():
    client = BasecampClient.__new__(BasecampClient)
    client.get_template = MagicMock(return_value={"name": "Existing"})
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "template-1", "name": "Existing"}

    with patch.object(client, "put", return_value=response) as put:
        assert client.update_template("template-1", description="New description") == {
            "id": "template-1", "name": "Existing"
        }

    put.assert_called_once_with(
        "templates/template-1.json",
        {"name": "Existing", "description": "New description"},
    )


def test_template_tools_are_registered_in_both_servers():
    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in MCPServer().tools}
    expected = {
        "get_templates", "get_template", "create_template", "update_template",
        "trash_template", "create_project_from_template", "get_project_construction",
    }
    assert expected <= fastmcp_names
    assert fastmcp_names == cli_names


def test_template_wrappers_return_structured_results():
    client = Mock()
    client.get_templates.return_value = [{"id": "template-1"}]
    client.get_template.return_value = {"id": "template-1"}
    client.create_template.return_value = {"id": "template-1"}
    client.update_template.return_value = {"id": "template-1"}
    client.trash_template.return_value = True
    client.create_project_from_template.return_value = {"id": "construction-1", "status": "pending"}
    client.get_project_construction.return_value = {"id": "construction-1", "status": "completed"}

    async def run():
        with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
            return (
                await basecamp_fastmcp.get_templates(),
                await basecamp_fastmcp.get_template("template-1"),
                await basecamp_fastmcp.create_template("Starter"),
                await basecamp_fastmcp.update_template("template-1", description="Updated"),
                await basecamp_fastmcp.trash_template("template-1"),
                await basecamp_fastmcp.create_project_from_template("template-1", "New"),
                await basecamp_fastmcp.get_project_construction("template-1", "construction-1"),
            )

    results = asyncio.run(run())
    assert results[0] == {"status": "success", "templates": [{"id": "template-1"}], "count": 1}
    assert results[1]["template"] == {"id": "template-1"}
    assert results[2]["template"] == {"id": "template-1"}
    assert results[3]["template"] == {"id": "template-1"}
    assert results[4]["status"] == "success"
    assert results[5]["construction"]["status"] == "pending"
    assert results[6]["construction"]["status"] == "completed"
