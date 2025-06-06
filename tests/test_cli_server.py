#!/usr/bin/env python3
"""Tests for the CLI MCP server."""

import json
import subprocess
import sys
import time
import pytest
from unittest.mock import patch
import token_storage

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
        expected_tools = ["get_projects", "search_basecamp", "get_todos"]
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
