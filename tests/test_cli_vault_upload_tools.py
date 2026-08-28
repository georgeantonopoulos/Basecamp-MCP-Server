"""CLI MCP parity tests for recording, vault, and upload reads."""

from unittest.mock import MagicMock, patch

from basecamp_client import DEFAULT_REQUEST_TIMEOUT, BasecampClient
from mcp_server_cli import MCPServer


def test_cli_registers_vault_and_upload_read_tools():
    tools = {tool["name"]: tool for tool in MCPServer().tools}

    assert tools["get_recordings"]["inputSchema"]["required"] == [
        "recording_type",
    ]
    assert tools["get_vaults"]["inputSchema"]["required"] == ["project_id", "vault_id"]
    assert tools["get_uploads"]["inputSchema"]["required"] == ["project_id"]
    assert tools["get_upload"]["inputSchema"]["required"] == ["project_id", "upload_id"]


@patch("mcp_server_cli.auth_manager.ensure_authenticated", return_value=True)
@patch(
    "mcp_server_cli.token_storage.get_token",
    return_value={"access_token": "token", "account_id": "12345"},
)
def test_cli_routes_vault_and_upload_reads(mock_get_token, mock_auth):
    server = MCPServer()

    with patch.object(BasecampClient, "get_recordings", return_value=[{"id": "vault-2"}]) as get_recordings:
        result = server._execute_tool(
            "get_recordings",
            {"recording_type": "Vault", "project_id": "project-1"},
        )

    assert result == {
        "status": "success",
        "recordings": [{"id": "vault-2"}],
        "count": 1,
    }
    get_recordings.assert_called_once_with(
        "Vault",
        "project-1",
        "active",
        "created_at",
        "desc",
    )

    with patch.object(
        BasecampClient,
        "get_recordings",
        return_value=[
            {"id": "one", "title": "Portrait"},
            {"id": "two", "title": "Screen 16:9"},
        ],
    ):
        result = server._execute_tool(
            "get_recordings",
            {
                "recording_type": "Document",
                "project_id": "project-1",
                "query": "16:9",
                "compact": True,
            },
        )

    assert result == {
        "status": "success",
        "recordings": [{"id": "two", "title": "Screen 16:9"}],
        "count": 1,
    }

    with patch.object(BasecampClient, "get_vaults", return_value=[{"id": "vault-2"}]) as get_vaults:
        result = server._execute_tool(
            "get_vaults",
            {"project_id": "project-1", "vault_id": "vault-1"},
        )

    assert result == {
        "status": "success",
        "vaults": [{"id": "vault-2"}],
        "count": 1,
    }
    get_vaults.assert_called_once_with("project-1", "vault-1")

    with patch.object(BasecampClient, "get_uploads", return_value=[{"id": "upload-1"}]) as get_uploads:
        result = server._execute_tool(
            "get_uploads",
            {"project_id": "project-1", "vault_id": "vault-2"},
        )

    assert result == {
        "status": "success",
        "uploads": [{"id": "upload-1"}],
        "count": 1,
    }
    get_uploads.assert_called_once_with("project-1", "vault-2")

    with patch.object(BasecampClient, "get_upload", return_value={"id": "upload-1"}) as get_upload:
        result = server._execute_tool(
            "get_upload",
            {"project_id": "project-1", "upload_id": "upload-1"},
        )

    assert result == {"status": "success", "upload": {"id": "upload-1"}}
    get_upload.assert_called_once_with("project-1", "upload-1")


def test_client_collection_reads_follow_basecamp_next_links():
    client = BasecampClient.__new__(BasecampClient)
    client.auth = MagicMock()
    client.headers = {"User-Agent": "test"}

    first = MagicMock(status_code=200, links={"next": {"url": "https://3.basecampapi.com/6164391/page-2"}})
    first.json.return_value = [{"id": "one"}]
    second = MagicMock(status_code=200, links={})
    second.json.return_value = [{"id": "two"}]

    with patch.object(client, "get", return_value=first) as first_get:
        with patch("basecamp_client.requests.get", return_value=second) as next_get:
            result = client.get_recordings("Vault", "project-1")

    assert result == [{"id": "one"}, {"id": "two"}]
    first_get.assert_called_once_with(
        "projects/recordings.json",
        params={
            "type": "Vault",
            "bucket": "project-1",
            "status": "active",
            "sort": "created_at",
            "direction": "desc",
        },
    )
    next_get.assert_called_once_with(
        "https://3.basecampapi.com/6164391/page-2",
        auth=client.auth,
        headers=client.headers,
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )


def test_recordings_can_be_listed_account_wide():
    client = BasecampClient.__new__(BasecampClient)
    with patch.object(client, "_get_paginated_collection", return_value=[{"id": "todo-1"}]) as collect:
        result = client.get_recordings("Todo")

    assert result == [{"id": "todo-1"}]
    collect.assert_called_once_with(
        "projects/recordings.json",
        params={
            "type": "Todo",
            "status": "active",
            "sort": "created_at",
            "direction": "desc",
        },
    )
