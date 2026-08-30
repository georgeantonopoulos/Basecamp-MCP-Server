#!/usr/bin/env python3
"""Line-oriented JSON-RPC compatibility transport for the Basecamp MCP server.

The FastMCP tool registry is the only catalog and dispatch implementation.
This module exists for clients that still launch the historical stdin/stdout
entry point.
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from basecamp_fastmcp import mcp as fastmcp_server

# Kept as compatibility imports for callers/tests that historically patched
# these modules through mcp_server_cli. Authentication itself lives in the
# FastMCP tool wrappers.
import auth_manager  # noqa: F401
import token_storage  # noqa: F401


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(PROJECT_ROOT, "mcp_cli_server.log")),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("mcp_cli_server")


def _json_default(value: Any) -> Any:
    """Serialize FastMCP/Pydantic content blocks for JSON-RPC transport."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "dict"):
        return value.dict()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _is_mcp_content_block(value: Any) -> bool:
    """Recognize typed MCP content blocks returned by FastMCP tools."""
    return (
        hasattr(value, "model_dump")
        and getattr(value, "type", None)
        in {"text", "image", "audio", "resource", "resource_link"}
    )


def _tool_result_content(result: Any) -> List[Dict[str, Any]]:
    """Preserve native MCP blocks while keeping ordinary results as text."""
    if isinstance(result, list) and result and all(
        _is_mcp_content_block(item) for item in result
    ):
        return [item.model_dump(mode="json", exclude_none=True) for item in result]
    return [{"type": "text", "text": json.dumps(result, indent=2, default=_json_default)}]


def _normalize_tool_result(result: Any) -> Any:
    """Give legacy clients a stable status field for tool-level failures."""
    if isinstance(result, dict) and "error" in result:
        result = dict(result)
        result.setdefault("status", "error")
    return result


def _rpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


class MCPServer:
    """Expose the FastMCP server through the legacy JSON-RPC line protocol."""

    def __init__(self):
        public_tools = asyncio.run(fastmcp_server.list_tools())
        self._fastmcp_tool_names = {tool.name for tool in public_tools}
        self.tools = self._get_available_tools(public_tools)
        logger.info("MCP CLI Server initialized with %d tools", len(self.tools))

    def _get_available_tools(self, public_tools) -> List[Dict[str, Any]]:
        """Derive the compatibility catalog from registered FastMCP tools."""
        return [
            {
                "name": tool.name,
                "description": tool.description or "",
                "inputSchema": tool.inputSchema,
            }
            for tool in public_tools
        ]

    def _execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Run a registered FastMCP tool with its normal validation path."""
        if tool_name not in self._fastmcp_tool_names:
            return {
                "error": "Unknown tool",
                "message": f"Tool '{tool_name}' is not supported",
            }
        try:
            result = asyncio.run(fastmcp_server.call_tool(tool_name, arguments))
            if isinstance(result, tuple) and len(result) == 2:
                content, structured = result
                if isinstance(structured, dict):
                    if set(structured) == {"result"}:
                        return structured["result"]
                    return structured
                return content
            return result
        except Exception as exc:
            logger.error("Error executing FastMCP tool %s: %s", tool_name, exc)
            return {"error": "Execution error", "message": str(exc)}

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle one JSON-RPC request or notification."""
        if not isinstance(request, dict):
            return _rpc_error(None, -32600, "Invalid Request")

        method = request.get("method")
        method_lower = method.lower() if isinstance(method, str) else ""
        is_notification = "id" not in request
        request_id = request.get("id")
        params = request.get("params", {})

        def response(payload):
            """Suppress JSON-RPC responses for notification messages."""
            return None if is_notification else payload

        if method_lower == "initialized":
            return None
        if method_lower in {"initialize", "tools/list", "listtools", "tools/call", "toolscall", "listofferings", "list_offerings", "loffering", "ping"} and not isinstance(params, dict):
            return response(_rpc_error(request_id, -32602, "Invalid params"))

        try:
            if method_lower == "initialize":
                return response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "basecamp-mcp-server", "version": "1.0.0"},
                    },
                })

            if method_lower in {"tools/list", "listtools"}:
                return response({"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tools}})

            if method_lower in {"tools/call", "toolscall"}:
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                if not isinstance(tool_name, str) or not tool_name:
                    return response(_rpc_error(request_id, -32602, "Invalid params: tool name is required"))
                if not isinstance(arguments, dict):
                    return response(_rpc_error(request_id, -32602, "Invalid params: arguments must be an object"))
                result = _normalize_tool_result(self._execute_tool(tool_name, arguments))
                return response({
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": _tool_result_content(result),
                        "isError": isinstance(result, dict) and result.get("status") == "error",
                    },
                })

            if method_lower in {"listofferings", "list_offerings", "loffering"}:
                offerings = [
                    {"name": tool["name"], "displayName": tool["name"], "description": tool["description"]}
                    for tool in self.tools
                ]
                return response({"jsonrpc": "2.0", "id": request_id, "result": {"offerings": offerings}})

            if method_lower == "ping":
                return response({"jsonrpc": "2.0", "id": request_id, "result": {}})

            return response(_rpc_error(request_id, -32601, f"Method not found: {method}"))
        except Exception as exc:
            logger.error("Error handling request: %s", exc)
            return response(_rpc_error(request_id, -32603, f"Internal error: {exc}"))

    def run(self) -> None:
        """Read one JSON request per line and write one JSON response per line."""
        logger.info("Starting MCP CLI server")
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                response = self.handle_request(json.loads(line))
            except json.JSONDecodeError:
                response = _rpc_error(None, -32700, "Parse error")
            except Exception as exc:
                logger.error("Unexpected error: %s", exc)
                response = _rpc_error(None, -32603, f"Internal error: {exc}")
            if response is not None:
                print(json.dumps(response, default=_json_default), flush=True)


if __name__ == "__main__":
    MCPServer().run()
