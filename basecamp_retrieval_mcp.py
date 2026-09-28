#!/usr/bin/env python3
"""Retrieval-first MCP entry point for the full Basecamp tool catalog.

Only four tools are advertised initially.  They discover and dispatch to the
canonical tools registered in ``basecamp_fastmcp.py``, so argument validation,
typed content, authentication, and business logic stay on one implementation
path.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from basecamp_fastmcp import mcp as full_mcp
from basecamp_tool_retrieval import (
    CATEGORY_BY_NAME,
    category_summaries,
    retrieve_tools,
    tool_access,
)


logger = logging.getLogger("basecamp_retrieval_mcp")

retrieval_mcp = FastMCP(
    "basecamp",
    instructions=(
        "Start with list_basecamp_categories or discover_basecamp_tools. "
        "Discover only the operations relevant to the current request, then "
        "invoke the named operation through its returned read or write executor."
    ),
)


async def _full_tools():
    return await full_mcp.list_tools()


async def _find_tool(name: str):
    for tool in await _full_tools():
        if tool.name == name:
            return tool
    return None


def _raise_if_tool_error(result: Any) -> Any:
    """Convert canonical error envelopes into MCP-visible tool failures."""
    if isinstance(result, dict) and (
        result.get("status") == "error" or "error" in result
    ):
        error = result.get("error", "Execution error")
        message = result.get("message", "The Basecamp operation failed")
        raise ToolError(f"{error}: {message}")
    return result


async def _dispatch(name: str, arguments: Dict[str, Any], expected_access: str) -> Any:
    if not isinstance(arguments, dict):
        raise ToolError("Invalid input: arguments must be an object")

    tool = await _find_tool(name)
    if tool is None:
        raise ToolError(
            f"Unknown tool: '{name}' is not a registered Basecamp tool. "
            "Discover it before calling."
        )

    actual_access = tool_access(name)
    if actual_access != expected_access:
        raise ToolError(
            f"Wrong executor: '{name}' is a {actual_access} tool; "
            f"use call_basecamp_{actual_access}_tool."
        )

    try:
        result = await full_mcp.call_tool(name, arguments)
        if isinstance(result, tuple) and len(result) == 2:
            content, structured = result
            if isinstance(structured, dict):
                if set(structured) == {"result"}:
                    return _raise_if_tool_error(structured["result"])
                return _raise_if_tool_error(structured)
            return content
        return _raise_if_tool_error(result)
    except ToolError:
        raise
    except Exception as exc:
        logger.error("Error executing discovered Basecamp tool %s: %s", name, exc)
        raise ToolError(f"Execution error: {exc}") from exc


@retrieval_mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def list_basecamp_categories() -> Dict[str, Any]:
    """List compact Basecamp tool categories and their read/write tool counts."""
    categories = category_summaries(await _full_tools())
    return {
        "status": "success",
        "categories": categories,
        "count": len(categories),
        "next_step": "Call discover_basecamp_tools with a category and/or natural-language intent.",
    }


@retrieval_mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
async def discover_basecamp_tools(
    intent: str,
    category: Optional[str] = None,
    access: Literal["read", "write", "all"] = "all",
    limit: int = 6,
) -> Dict[str, Any]:
    """Find a small set of Basecamp operations relevant to the current task.

    Args:
        intent: Natural-language action, for example "find overdue todos".
        category: Optional category name from list_basecamp_categories.
        access: Restrict matches to read tools, write tools, or all tools.
        limit: Maximum matches to return, between 1 and 12.
    """
    try:
        matches = retrieve_tools(
            await _full_tools(),
            intent=intent,
            category=category,
            access=access,
            limit=limit,
            include_schema=True,
        )
    except ValueError as exc:
        raise ToolError(f"Invalid input: {exc}") from exc

    return {
        "status": "success",
        "intent": intent,
        "category": category,
        "matches": matches,
        "count": len(matches),
        "instructions": (
            "Choose one match and call the executor named in that match with "
            "its tool name and arguments conforming to input_schema."
            if matches
            else "No close match was found. List categories or retry with a broader intent."
        ),
    }


@retrieval_mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def call_basecamp_read_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute one discovered read-only Basecamp tool through its original schema."""
    return await _dispatch(name, arguments, "read")


@retrieval_mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True,
    )
)
async def call_basecamp_write_tool(name: str, arguments: Dict[str, Any]) -> Any:
    """Execute one discovered Basecamp mutation through its original schema."""
    return await _dispatch(name, arguments, "write")


if __name__ == "__main__":
    logger.info(
        "Starting retrieval-first Basecamp MCP server with %d categories",
        len(CATEGORY_BY_NAME),
    )
    retrieval_mcp.run(transport="stdio")
