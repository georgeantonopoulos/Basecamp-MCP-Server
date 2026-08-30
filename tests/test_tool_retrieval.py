"""Tests for the compact category-based Basecamp MCP entry point."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from mcp.types import ImageContent, TextContent
from mcp.server.fastmcp.exceptions import ToolError

import basecamp_retrieval_mcp
import basecamp_tool_retrieval
import generate_claude_desktop_config
import generate_codex_config
import generate_cursor_config


def _run(awaitable):
    return asyncio.run(awaitable)


def test_retrieval_server_exposes_only_compact_public_surface():
    tools = _run(basecamp_retrieval_mcp.retrieval_mcp.list_tools())

    assert [tool.name for tool in tools] == [
        "list_basecamp_categories",
        "discover_basecamp_tools",
        "call_basecamp_read_tool",
        "call_basecamp_write_tool",
    ]
    serialized = json.dumps(
        [tool.model_dump(mode="json", by_alias=True) for tool in tools]
    )
    assert len(serialized.encode("utf-8")) < 5_000

    by_name = {tool.name: tool for tool in tools}
    assert by_name["call_basecamp_read_tool"].annotations.readOnlyHint is True
    assert by_name["call_basecamp_write_tool"].annotations.destructiveHint is True


def test_every_canonical_tool_is_available_through_one_category_and_executor():
    tools = _run(basecamp_retrieval_mcp.full_mcp.list_tools())
    categories = basecamp_tool_retrieval.category_summaries(tools)

    assert len(tools) == 210
    assert sum(category["total_tools"] for category in categories) == len(tools)
    assert all(category["total_tools"] > 0 for category in categories)
    assert {
        basecamp_tool_retrieval.tool_category(tool.name) for tool in tools
    } == set(basecamp_tool_retrieval.CATEGORY_BY_NAME)
    assert {
        basecamp_tool_retrieval.tool_access(tool.name) for tool in tools
    } == {"read", "write"}


def test_category_listing_is_compact_and_counted():
    result = _run(basecamp_retrieval_mcp.list_basecamp_categories())

    assert result["status"] == "success"
    assert result["count"] == 11
    assert sum(item["total_tools"] for item in result["categories"]) == 210
    assert {item["name"] for item in result["categories"]} == set(
        basecamp_tool_retrieval.CATEGORY_BY_NAME
    )


def test_discovery_ranks_relevant_tools_and_returns_original_schemas():
    result = _run(
        basecamp_retrieval_mcp.discover_basecamp_tools(
            "find overdue todos", access="read", limit=4
        )
    )

    assert result["status"] == "success"
    assert result["matches"][0]["name"] == "get_overdue_todos"
    assert all(match["access"] == "read" for match in result["matches"])
    assert all(match["executor"] == "call_basecamp_read_tool" for match in result["matches"])
    assert all(match["input_schema"]["type"] == "object" for match in result["matches"])


def test_discovery_uses_category_and_write_filter():
    result = _run(
        basecamp_retrieval_mcp.discover_basecamp_tools(
            "create a message",
            category="messages_comments",
            access="write",
            limit=3,
        )
    )

    assert result["matches"][0]["name"] == "create_message"
    assert all(match["category"] == "messages_comments" for match in result["matches"])
    assert all(match["access"] == "write" for match in result["matches"])


def test_discovery_rejects_invalid_bounds_and_categories():
    with pytest.raises(ToolError, match="Unknown category"):
        _run(
            basecamp_retrieval_mcp.discover_basecamp_tools(
                "find todos", category="not-a-category"
            )
        )
    with pytest.raises(ToolError, match="between 1 and 12"):
        _run(
            basecamp_retrieval_mcp.discover_basecamp_tools(
                "find todos", limit=13
            )
        )


def test_discovery_does_not_return_unrelated_fallback_tools():
    result = _run(
        basecamp_retrieval_mcp.discover_basecamp_tools(
            "quantum submarine telemetry", limit=6
        )
    )

    assert result["matches"] == []
    assert "broader intent" in result["instructions"]


def test_read_dispatcher_uses_canonical_fastmcp_validation_path():
    expected = {"status": "success", "projects": [], "count": 0}
    with patch.object(
        basecamp_retrieval_mcp.full_mcp,
        "call_tool",
        new=AsyncMock(return_value=([], {"result": expected})),
    ) as call_tool:
        result = _run(
            basecamp_retrieval_mcp.call_basecamp_read_tool("get_projects", {})
        )

    assert result == expected
    call_tool.assert_awaited_once_with("get_projects", {})


def test_dispatchers_reject_the_wrong_access_boundary():
    with pytest.raises(ToolError, match="call_basecamp_read_tool"):
        _run(
            basecamp_retrieval_mcp.call_basecamp_write_tool("get_projects", {})
        )
    with pytest.raises(ToolError, match="call_basecamp_write_tool"):
        _run(
            basecamp_retrieval_mcp.call_basecamp_read_tool(
                "create_project", {"name": "Example"}
            )
        )


def test_canonical_error_envelope_becomes_tool_error():
    with patch.object(
        basecamp_retrieval_mcp.full_mcp,
        "call_tool",
        new=AsyncMock(
            return_value=(
                [],
                {"result": {"status": "error", "error": "Execution error", "message": "boom"}},
            )
        ),
    ):
        with pytest.raises(ToolError, match="Execution error: boom"):
            _run(
                basecamp_retrieval_mcp.call_basecamp_read_tool(
                    "get_projects", {}
                )
            )


def test_stdio_marks_dispatch_rejection_as_mcp_error():
    project_root = Path(__file__).resolve().parents[1]
    requests = "\n".join(
        [
            json.dumps({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            }),
            json.dumps({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }),
            json.dumps({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "call_basecamp_read_tool",
                    "arguments": {"name": "create_project", "arguments": {"name": "Example"}},
                },
            }),
        ]
    ) + "\n"

    completed = subprocess.run(
        [sys.executable, str(project_root / "basecamp_retrieval_mcp.py")],
        cwd=project_root,
        input=requests,
        text=True,
        capture_output=True,
        check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    tool_response = next(response for response in responses if response.get("id") == 2)

    assert tool_response["result"]["isError"] is True
    assert "Wrong executor" in tool_response["result"]["content"][0]["text"]


def test_dispatch_preserves_typed_content_from_canonical_tool():
    blocks = [
        TextContent(type="text", text="preview"),
        ImageContent(type="image", data="aGVsbG8=", mimeType="image/png"),
    ]
    with patch.object(
        basecamp_retrieval_mcp.full_mcp,
        "call_tool",
        new=AsyncMock(return_value=(blocks, None)),
    ):
        result = _run(
            basecamp_retrieval_mcp.call_basecamp_read_tool(
                "download_upload", {"project_id": "1", "upload_id": "2"}
            )
        )

    assert result == blocks


def test_config_generators_default_to_retrieval_and_offer_full_mode(tmp_path):
    _, default_script, _ = generate_codex_config.get_server_details(
        tmp_path, use_legacy=False
    )
    _, full_script, _ = generate_codex_config.get_server_details(
        tmp_path, use_legacy=False, use_full=True
    )
    _, legacy_script, _ = generate_codex_config.get_server_details(
        tmp_path, use_legacy=True
    )

    assert default_script == tmp_path / "basecamp_retrieval_mcp.py"
    assert full_script == tmp_path / "basecamp_fastmcp.py"
    assert legacy_script == tmp_path / "mcp_server_cli.py"

    cursor_default, _ = generate_cursor_config.generate_config()
    cursor_full, _ = generate_cursor_config.generate_config(use_full=True)
    assert cursor_default["mcpServers"]["basecamp"]["args"][0].endswith(
        "basecamp_retrieval_mcp.py"
    )
    assert cursor_full["mcpServers"]["basecamp"]["args"][0].endswith(
        "basecamp_fastmcp.py"
    )

    assert generate_claude_desktop_config.get_server_script(tmp_path).endswith(
        "basecamp_retrieval_mcp.py"
    )
    assert generate_claude_desktop_config.get_server_script(
        tmp_path, use_full=True
    ).endswith("basecamp_fastmcp.py")
    assert generate_claude_desktop_config.get_server_script(
        tmp_path, use_legacy=True
    ).endswith("mcp_server_cli.py")
