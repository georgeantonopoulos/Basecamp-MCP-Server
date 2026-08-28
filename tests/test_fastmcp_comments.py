"""Tests for the FastMCP comment tools."""

import asyncio
import inspect
from unittest.mock import Mock, patch

import basecamp_fastmcp


def run_tool(tool, *args):
    return asyncio.run(tool(*args))


def test_comment_tools_are_registered_with_expected_signatures():
    tools = basecamp_fastmcp.mcp._tool_manager._tools

    assert {"get_comment", "update_comment", "delete_comment"} <= set(tools)
    assert list(inspect.signature(tools["get_comment"].fn).parameters) == [
        "comment_id",
        "project_id",
    ]
    assert list(inspect.signature(tools["update_comment"].fn).parameters) == [
        "comment_id",
        "project_id",
        "content",
    ]
    assert list(inspect.signature(tools["delete_comment"].fn).parameters) == [
        "comment_id",
        "project_id",
    ]


@patch("basecamp_fastmcp._get_basecamp_client")
def test_get_comment_returns_compatibility_shape(mock_get_client):
    client = Mock()
    client.get_comment.return_value = {"id": "comment-1", "content": "Hello"}
    mock_get_client.return_value = client

    result = run_tool(basecamp_fastmcp.get_comment, "comment-1", "project-1")

    assert result == {
        "status": "success",
        "comment": {"id": "comment-1", "content": "Hello"},
    }
    client.get_comment.assert_called_once_with("comment-1", "project-1")


@patch("basecamp_fastmcp._get_basecamp_client")
def test_update_comment_returns_compatibility_shape(mock_get_client):
    client = Mock()
    client.update_comment.return_value = {"id": "comment-1", "content": "Updated"}
    mock_get_client.return_value = client

    result = run_tool(
        basecamp_fastmcp.update_comment,
        "comment-1",
        "project-1",
        "Updated",
    )

    assert result == {
        "status": "success",
        "comment": {"id": "comment-1", "content": "Updated"},
        "message": "Comment updated successfully",
    }
    client.update_comment.assert_called_once_with("comment-1", "project-1", "Updated")


@patch("basecamp_fastmcp._get_basecamp_client")
def test_delete_comment_returns_compatibility_shape(mock_get_client):
    client = Mock()
    client.delete_comment.return_value = True
    mock_get_client.return_value = client

    result = run_tool(basecamp_fastmcp.delete_comment, "comment-1", "project-1")

    assert result == {
        "status": "success",
        "message": "Comment deleted successfully",
    }
    client.delete_comment.assert_called_once_with("comment-1", "project-1")


@patch("basecamp_fastmcp._get_basecamp_client")
def test_comment_tools_return_execution_errors(mock_get_client):
    client = Mock()
    client.get_comment.side_effect = RuntimeError("boom")
    mock_get_client.return_value = client

    result = run_tool(basecamp_fastmcp.get_comment, "comment-1", "project-1")

    assert result == {"error": "Execution error", "message": "boom"}
