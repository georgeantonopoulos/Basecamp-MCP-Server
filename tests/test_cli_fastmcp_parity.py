"""Regression tests for the shared FastMCP/legacy CLI tool surface."""

import asyncio
from unittest.mock import AsyncMock, patch

import basecamp_fastmcp
from mcp.types import ImageContent, TextContent
from mcp_server_cli import MCPServer, _tool_result_content


def test_cli_advertises_every_fastmcp_tool():
    server = MCPServer()

    fastmcp_names = set(basecamp_fastmcp.mcp._tool_manager._tools)
    cli_names = {tool["name"] for tool in server.tools}

    assert cli_names == fastmcp_names
    assert server.tools == [
        {
            "name": tool.name,
            "description": tool.description or "",
            "inputSchema": tool.parameters,
        }
        for tool in basecamp_fastmcp.mcp._tool_manager._tools.values()
    ]


def test_cli_routes_new_tools_through_fastmcp_validation():
    server = MCPServer()
    tool = server._fastmcp_tools["get_message_board"]
    expected = {"status": "success", "message_board": {"id": "board-1"}}

    with patch.object(type(tool), "run", new=AsyncMock(return_value=expected)) as run:
        result = server._execute_tool(
            "get_message_board",
            {"project_id": "project-1"},
        )

    assert result == expected
    run.assert_awaited_once_with({"project_id": "project-1"})


def test_cli_routes_original_tools_through_fastmcp_too():
    server = MCPServer()
    tool = server._fastmcp_tools["get_projects"]
    expected = {"status": "success", "projects": [], "count": 0}

    with patch.object(type(tool), "run", new=AsyncMock(return_value=expected)) as run:
        result = server._execute_tool("get_projects", {})

    assert result == expected
    run.assert_awaited_once_with({})


def test_account_and_project_context_tools_return_counted_results():
    client = type(
        "ClientStub",
        (),
        {
            "get_people": lambda self: [{"id": "person-1"}],
            "get_campfires": lambda self, project_id: [{"id": "chat-1"}],
        },
    )()

    with patch.object(basecamp_fastmcp, "_get_basecamp_client", return_value=client):
        people = asyncio.run(basecamp_fastmcp.get_people())
        campfires = asyncio.run(basecamp_fastmcp.get_campfires("project-1"))

    assert people == {
        "status": "success",
        "people": [{"id": "person-1"}],
        "count": 1,
    }
    assert campfires == {
        "status": "success",
        "campfires": [{"id": "chat-1"}],
        "count": 1,
    }


def test_legacy_bridge_preserves_typed_mcp_content_blocks():
    blocks = [
        TextContent(type="text", text="preview"),
        ImageContent(type="image", data="aGVsbG8=", mimeType="image/png"),
    ]

    assert _tool_result_content(blocks) == [
        {"type": "text", "text": "preview"},
        {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
    ]


def test_tools_call_response_keeps_native_content_blocks():
    server = MCPServer()
    blocks = [
        TextContent(type="text", text="preview"),
        ImageContent(type="image", data="aGVsbG8=", mimeType="image/png"),
    ]

    with patch.object(server, "_execute_tool", return_value=blocks):
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "download_upload", "arguments": {}},
        })

    assert response["result"]["content"] == [
        {"type": "text", "text": "preview"},
        {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
    ]
    assert response["result"]["isError"] is False


def test_tools_call_marks_tool_failures_as_errors():
    server = MCPServer()

    with patch.object(server, "_execute_tool", return_value={"error": "Execution error", "message": "boom"}):
        response = server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_projects", "arguments": {}},
        })

    assert response["result"]["isError"] is True
    assert response["result"]["content"] == [{
        "type": "text",
        "text": '{\n  "error": "Execution error",\n  "message": "boom",\n  "status": "error"\n}',
    }]


def test_cli_rejects_malformed_tool_call_params_as_invalid_params():
    server = MCPServer()

    response = server.handle_request({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"arguments": {}},
    })

    assert response["error"] == {
        "code": -32602,
        "message": "Invalid params: tool name is required",
    }


def test_cli_rejects_non_object_params():
    server = MCPServer()

    response = server.handle_request({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/list",
        "params": [],
    })

    assert response["error"] == {"code": -32602, "message": "Invalid params"}


def test_cli_suppresses_responses_for_jsonrpc_notifications():
    server = MCPServer()

    with patch.object(server, "_execute_tool") as execute:
        assert server.handle_request({
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": "get_projects", "arguments": {}},
        }) is None
        assert server.handle_request({
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
        }) is None
        assert server.handle_request({
            "jsonrpc": "2.0",
            "method": "ping",
            "params": {},
        }) is None

    execute.assert_called_once_with("get_projects", {})
