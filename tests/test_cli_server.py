#!/usr/bin/env python3
"""Tests for the CLI MCP server."""

import json
import os
import subprocess
import sys
import time
import pytest
from unittest.mock import patch, Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import token_storage
from mcp_server_cli import MCPServer

def test_cli_server_initialize():
    """Test that the CLI server responds to initialize requests."""
    # Create a mock request
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }

    # Start the CLI server process
    proc = subprocess.Popen(
        [sys.executable, "mcp_server_cli.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Send the request
        stdout, stderr = proc.communicate(
            input=json.dumps(request) + "\n",
            timeout=10
        )

        # Parse the response
        response = json.loads(stdout.strip())

        # Check the response
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert "protocolVersion" in response["result"]
        assert "capabilities" in response["result"]
        assert "serverInfo" in response["result"]

    finally:
        if proc.poll() is None:
            proc.terminate()

def test_cli_server_tools_list():
    """Test that the CLI server returns available tools."""
    # Create requests
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }

    tools_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    }

    # Start the CLI server process
    proc = subprocess.Popen(
        [sys.executable, "mcp_server_cli.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Send both requests
        input_data = json.dumps(init_request) + "\n" + json.dumps(tools_request) + "\n"
        stdout, stderr = proc.communicate(
            input=input_data,
            timeout=10
        )

        # Parse responses (we get two lines)
        lines = stdout.strip().split('\n')
        assert len(lines) >= 2

        # Check the tools list response (second response)
        tools_response = json.loads(lines[1])

        assert tools_response["jsonrpc"] == "2.0"
        assert tools_response["id"] == 2
        assert "result" in tools_response
        assert "tools" in tools_response["result"]

        tools = tools_response["result"]["tools"]
        assert isinstance(tools, list)
        assert len(tools) > 0

        # Check that expected tools are present
        tool_names = [tool["name"] for tool in tools]
        expected_tools = ["get_projects", "search_basecamp", "get_todos", "global_search", "create_comment"]
        for expected_tool in expected_tools:
            assert expected_tool in tool_names

    finally:
        if proc.poll() is None:
            proc.terminate()

@patch.object(token_storage, 'get_token')
def test_cli_server_tool_call_no_auth(mock_get_token):
    """Test tool call when not authenticated."""
    # Note: The mock doesn't work across processes, so this test checks
    # that the CLI server handles authentication errors gracefully

    # Create requests
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }

    tool_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "get_projects",
            "arguments": {}
        }
    }

    # Start the CLI server process
    proc = subprocess.Popen(
        [sys.executable, "mcp_server_cli.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Send both requests
        input_data = json.dumps(init_request) + "\n" + json.dumps(tool_request) + "\n"
        stdout, stderr = proc.communicate(
            input=input_data,
            timeout=10
        )

        # Parse responses
        lines = stdout.strip().split('\n')
        assert len(lines) >= 2

        # Check the tool call response (second response)
        tool_response = json.loads(lines[1])

        assert tool_response["jsonrpc"] == "2.0"
        assert tool_response["id"] == 2
        assert "result" in tool_response
        assert "content" in tool_response["result"]

        # The content should contain some kind of response (either data or error)
        content_text = tool_response["result"]["content"][0]["text"]
        content_data = json.loads(content_text)

        # Since we have valid OAuth tokens, this might succeed or fail
        # We just check that we get a valid JSON response
        assert isinstance(content_data, dict)

    finally:
        if proc.poll() is None:
            proc.terminate()

def test_cli_server_global_search_call_no_auth(tmp_path):
    """Test global search tool call without authentication."""
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {}
    }

    tool_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "global_search",
            "arguments": {"query": "test"}
        }
    }

    env = os.environ.copy()
    env["BASECAMP_MCP_TOKEN_FILE"] = str(tmp_path / "missing-oauth-tokens.json")

    proc = subprocess.Popen(
        [sys.executable, "mcp_server_cli.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    try:
        input_data = json.dumps(init_request) + "\n" + json.dumps(tool_request) + "\n"
        stdout, stderr = proc.communicate(
            input=input_data,
            timeout=10
        )

        lines = stdout.strip().split('\n')
        assert len(lines) >= 2

        tool_response = json.loads(lines[1])

        assert tool_response["jsonrpc"] == "2.0"
        assert tool_response["id"] == 2
        assert "result" in tool_response
        assert "content" in tool_response["result"]

    finally:
        if proc.poll() is None:
            proc.terminate()

def test_cli_server_invalid_method():
    """Test that the CLI server handles invalid methods."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "invalid_method",
        "params": {}
    }

    # Start the CLI server process
    proc = subprocess.Popen(
        [sys.executable, "mcp_server_cli.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Send the request
        stdout, stderr = proc.communicate(
            input=json.dumps(request) + "\n",
            timeout=10
        )

        # Parse the response
        response = json.loads(stdout.strip())

        # Check the error response
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "error" in response
        assert response["error"]["code"] == -32601  # Method not found

    finally:
        if proc.poll() is None:
            proc.terminate()


# --- Reports API tools (parity with basecamp_fastmcp.py) ---------------------
#
# The legacy CLI server is kept for compatibility, so the three Reports tools
# added to the FastMCP server must also be listed in tools/list and dispatch
# through _execute_tool() with matching response shapes. These tests exercise
# the MCPServer class in-process with a mocked Basecamp client (no network).

REPORT_TOOLS = ["get_assignable_people", "get_person_assignments", "get_overdue_todos"]


def test_report_tools_registered_in_tools_list():
    """The three Reports tools appear in the CLI tools/list."""
    server = MCPServer()
    tools_by_name = {tool["name"]: tool for tool in server.tools}

    for name in REPORT_TOOLS:
        assert name in tools_by_name, f"{name} missing from tools/list"

    # get_person_assignments requires person_id and constrains group_by to the
    # two API-supported values (parity with the FastMCP Literal type).
    schema = tools_by_name["get_person_assignments"]["inputSchema"]
    assert schema["required"] == ["person_id"]
    assert schema["properties"]["group_by"]["enum"] == ["bucket", "date"]


@patch.object(MCPServer, "_get_basecamp_client")
def test_dispatch_get_assignable_people(mock_get_client):
    """get_assignable_people dispatches and returns people + count."""
    client = Mock()
    client.get_assignable_people.return_value = [{"id": 1}, {"id": 2}]
    mock_get_client.return_value = client

    result = MCPServer()._execute_tool("get_assignable_people", {})

    client.get_assignable_people.assert_called_once_with()
    assert result["status"] == "success"
    assert result["people"] == [{"id": 1}, {"id": 2}]
    assert result["count"] == 2


@patch.object(MCPServer, "_get_basecamp_client")
def test_dispatch_get_person_assignments(mock_get_client):
    """get_person_assignments passes person_id + group_by and unpacks report."""
    client = Mock()
    client.get_person_assignments.return_value = {
        "person": {"id": 42},
        "grouped_by": "date",
        "todos": [{"id": 10}, {"id": 11}],
    }
    mock_get_client.return_value = client

    result = MCPServer()._execute_tool(
        "get_person_assignments", {"person_id": "42", "group_by": "date"}
    )

    client.get_person_assignments.assert_called_once_with("42", "date")
    assert result["status"] == "success"
    assert result["person"] == {"id": 42}
    assert result["grouped_by"] == "date"
    assert result["todos"] == [{"id": 10}, {"id": 11}]
    assert result["count"] == 2


@patch.object(MCPServer, "_get_basecamp_client")
def test_dispatch_get_person_assignments_without_group_by(mock_get_client):
    """group_by defaults to None when the argument is omitted."""
    client = Mock()
    client.get_person_assignments.return_value = {"person": {}, "todos": []}
    mock_get_client.return_value = client

    result = MCPServer()._execute_tool("get_person_assignments", {"person_id": "7"})

    client.get_person_assignments.assert_called_once_with("7", None)
    assert result["status"] == "success"
    assert result["count"] == 0


@patch.object(MCPServer, "_get_basecamp_client")
def test_dispatch_get_overdue_todos(mock_get_client):
    """get_overdue_todos dispatches and wraps the report under 'overdue'."""
    client = Mock()
    report = {"under_a_week_late": [{"id": 1}], "over_a_week_late": []}
    client.get_overdue_todos.return_value = report
    mock_get_client.return_value = client

    result = MCPServer()._execute_tool("get_overdue_todos", {})

    client.get_overdue_todos.assert_called_once_with()
    assert result["status"] == "success"
    assert result["overdue"] == report
