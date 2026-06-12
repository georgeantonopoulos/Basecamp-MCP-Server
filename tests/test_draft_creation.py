import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from basecamp_client import BasecampClient
from mcp_server_cli import MCPServer


def _client():
    return BasecampClient(
        access_token="test-token",
        account_id="12345",
        user_agent="test-agent",
        auth_mode="oauth",
    )


def _created_response(payload):
    response = MagicMock()
    response.status_code = 201
    response.json.return_value = payload
    return response


def test_create_message_publishes_by_default():
    client = _client()

    with patch("basecamp_client.requests.post", return_value=_created_response({"id": "msg-1"})) as mock_post:
        result = client.create_message(
            "project-1",
            "Kickoff",
            "<div>Hello</div>",
            message_board_id="board-1",
        )

    assert result == {"id": "msg-1"}
    assert mock_post.call_args.kwargs["json"] == {
        "subject": "Kickoff",
        "content": "<div>Hello</div>",
        "status": "active",
    }


def test_create_message_draft_omits_status():
    client = _client()

    with patch("basecamp_client.requests.post", return_value=_created_response({"id": "msg-1"})) as mock_post:
        result = client.create_message(
            "project-1",
            "Kickoff",
            "<div>Hello</div>",
            message_board_id="board-1",
            status=None,
        )

    assert result == {"id": "msg-1"}
    assert mock_post.call_args.kwargs["json"] == {
        "subject": "Kickoff",
        "content": "<div>Hello</div>",
    }


def test_create_document_draft_omits_status():
    client = _client()

    with patch("basecamp_client.requests.post", return_value=_created_response({"id": "doc-1"})) as mock_post:
        result = client.create_document(
            "project-1",
            "vault-1",
            "Plan",
            "<div>Draft</div>",
            status=None,
        )

    assert result == {"id": "doc-1"}
    assert mock_post.call_args.kwargs["json"] == {
        "title": "Plan",
        "content": "<div>Draft</div>",
    }


def test_cli_schema_exposes_publish_for_draft_tools():
    tools = {tool["name"]: tool for tool in MCPServer().tools}

    message_schema = tools["create_message"]["inputSchema"]["properties"]
    document_schema = tools["create_document"]["inputSchema"]["properties"]

    assert message_schema["publish"]["type"] == "boolean"
    assert document_schema["publish"]["type"] == "boolean"
    assert "create_draft_message" in tools
    assert "create_draft_document" in tools
    assert "publish" not in tools["create_draft_message"]["inputSchema"]["properties"]
    assert "publish" not in tools["create_draft_document"]["inputSchema"]["properties"]


@patch("mcp_server_cli.auth_manager.ensure_authenticated", return_value=True)
@patch("mcp_server_cli.token_storage.get_token", return_value={"access_token": "token", "account_id": "12345"})
def test_cli_create_message_draft_passes_status_none(mock_get_token, mock_auth):
    server = MCPServer()

    with patch.object(BasecampClient, "create_message", return_value={"id": "msg-1"}) as mock_create:
        result = server._execute_tool(
            "create_message",
            {
                "project_id": "project-1",
                "subject": "Kickoff",
                "content": "<div>Hello</div>",
                "message_board_id": "board-1",
                "publish": False,
            },
        )

    assert result["status"] == "success"
    assert result["result"] == "Message 'Kickoff' drafted successfully"
    mock_create.assert_called_once_with(
        "project-1",
        "Kickoff",
        "<div>Hello</div>",
        message_board_id="board-1",
        category_id=None,
        status=None,
    )


@patch("mcp_server_cli.auth_manager.ensure_authenticated", return_value=True)
@patch("mcp_server_cli.token_storage.get_token", return_value={"access_token": "token", "account_id": "12345"})
def test_cli_create_draft_message_passes_status_none(mock_get_token, mock_auth):
    server = MCPServer()

    with patch.object(BasecampClient, "create_message", return_value={"id": "msg-1"}) as mock_create:
        result = server._execute_tool(
            "create_draft_message",
            {
                "project_id": "project-1",
                "subject": "Kickoff",
                "content": "<div>Hello</div>",
                "message_board_id": "board-1",
            },
        )

    assert result["status"] == "success"
    assert result["result"] == "Message 'Kickoff' drafted successfully"
    mock_create.assert_called_once_with(
        "project-1",
        "Kickoff",
        "<div>Hello</div>",
        message_board_id="board-1",
        category_id=None,
        status=None,
    )


@patch("mcp_server_cli.auth_manager.ensure_authenticated", return_value=True)
@patch("mcp_server_cli.token_storage.get_token", return_value={"access_token": "token", "account_id": "12345"})
def test_cli_create_document_draft_passes_status_none(mock_get_token, mock_auth):
    server = MCPServer()

    with patch.object(BasecampClient, "create_document", return_value={"id": "doc-1"}) as mock_create:
        result = server._execute_tool(
            "create_document",
            {
                "project_id": "project-1",
                "vault_id": "vault-1",
                "title": "Plan",
                "content": "<div>Draft</div>",
                "publish": False,
            },
        )

    assert result["status"] == "success"
    assert result["result"] == "Document 'Plan' drafted successfully"
    mock_create.assert_called_once_with(
        "project-1",
        "vault-1",
        "Plan",
        "<div>Draft</div>",
        status=None,
    )


@patch("mcp_server_cli.auth_manager.ensure_authenticated", return_value=True)
@patch("mcp_server_cli.token_storage.get_token", return_value={"access_token": "token", "account_id": "12345"})
def test_cli_create_draft_document_passes_status_none(mock_get_token, mock_auth):
    server = MCPServer()

    with patch.object(BasecampClient, "create_document", return_value={"id": "doc-1"}) as mock_create:
        result = server._execute_tool(
            "create_draft_document",
            {
                "project_id": "project-1",
                "vault_id": "vault-1",
                "title": "Plan",
                "content": "<div>Draft</div>",
            },
        )

    assert result["status"] == "success"
    assert result["result"] == "Document 'Plan' drafted successfully"
    mock_create.assert_called_once_with(
        "project-1",
        "vault-1",
        "Plan",
        "<div>Draft</div>",
        status=None,
    )
