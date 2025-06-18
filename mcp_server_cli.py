#!/usr/bin/env python3
"""
Command-line MCP server for Basecamp integration with Cursor.

This server implements the MCP (Model Context Protocol) via stdin/stdout
as expected by Cursor.
"""

import json
import sys
import logging
from typing import Any, Dict, List, Optional
from basecamp_client import BasecampClient
from search_utils import BasecampSearch
import token_storage
import os
from dotenv import load_dotenv

# Determine project root (directory containing this script)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# Explicitly load .env from the project root
DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(DOTENV_PATH)

# Log file in the project directory
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, 'mcp_cli_server.log')
# Set up logging to file AND stderr
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler(sys.stderr)  # Added StreamHandler for stderr
    ]
)
logger = logging.getLogger('mcp_cli_server')

class MCPServer:
    """MCP server implementing the Model Context Protocol for Cursor."""

    def __init__(self):
        self.tools = self._get_available_tools()
        logger.info("MCP CLI Server initialized")

    def _get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools for Basecamp."""
        return [
            {
                "name": "get_projects",
                "description": "Get all Basecamp projects",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_project",
                "description": "Get details for a specific project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "get_todolists",
                "description": "Get todo lists for a project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "get_todos",
                "description": "Get todos from a todo list",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "todolist_id": {"type": "string", "description": "The todo list ID"},
                    },
                    "required": ["project_id", "todolist_id"]
                }
            },
            {
                "name": "search_basecamp",
                "description": "Search across Basecamp projects, todos, and messages",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "project_id": {"type": "string", "description": "Optional project ID to limit search scope"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "global_search",
                "description": "Search projects, todos and campfire messages across all projects",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "get_comments",
                "description": "Get comments for a Basecamp item",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "recording_id": {"type": "string", "description": "The item ID"},
                        "project_id": {"type": "string", "description": "The project ID"}
                    },
                    "required": ["recording_id", "project_id"]
                }
            },
            {
                "name": "get_campfire_lines",
                "description": "Get recent messages from a Basecamp campfire (chat room)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "campfire_id": {"type": "string", "description": "The campfire/chat room ID"}
                    },
                    "required": ["project_id", "campfire_id"]
                }
            },
            {
                "name": "get_daily_check_ins",
                "description": "Get project's daily checking questionnaire",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "page": {"type": "integer", "description": "Page number paginated response"}
                    }
                },
                "required": ["project_id"]
            },
            {
                "name": "get_question_answers",
                "description": "Get answers on daily check-in question",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "question_id": {"type": "string", "description": "The question ID"},
                        "page": {"type": "integer", "description": "Page number paginated response"}
                    }
                },
                "required": ["project_id", "question_id"]
            }
        ]

    def _get_basecamp_client(self) -> Optional[BasecampClient]:
        """Get authenticated Basecamp client."""
        try:
            token_data = token_storage.get_token()
            logger.debug(f"Token data retrieved: {token_data}")

            if not token_data or not token_data.get('access_token'):
                logger.error("No OAuth token available")
                return None

            # Check if token is expired
            if token_storage.is_token_expired():
                logger.error("OAuth token has expired")
                return None

            # Get account_id from token data first, then fall back to env var
            account_id = token_data.get('account_id') or os.getenv('BASECAMP_ACCOUNT_ID')

            # Set a default user agent if none is provided
            user_agent = os.getenv('USER_AGENT') or "Basecamp MCP Server (cursor@example.com)"

            if not account_id:
                logger.error(f"Missing account_id. Token data: {token_data}, Env BASECAMP_ACCOUNT_ID: {os.getenv('BASECAMP_ACCOUNT_ID')}")
                return None

            logger.debug(f"Creating Basecamp client with account_id: {account_id}, user_agent: {user_agent}")

            return BasecampClient(
                access_token=token_data['access_token'],
                account_id=account_id,
                user_agent=user_agent,
                auth_mode='oauth'
            )
        except Exception as e:
            logger.error(f"Error creating Basecamp client: {e}")
            return None

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an MCP request."""
        method = request.get("method")
        # Normalize method name for cursor compatibility
        method_lower = method.lower() if isinstance(method, str) else ''
        params = request.get("params", {})
        request_id = request.get("id")

        logger.info(f"Handling request: {method}")

        try:
            if method_lower == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "basecamp-mcp-server",
                            "version": "1.0.0"
                        }
                    }
                }

            elif method_lower == "initialized":
                # This is a notification, no response needed
                logger.info("Received initialized notification")
                return None

            elif method_lower in ("tools/list", "listtools"):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": self.tools
                    }
                }

            elif method_lower in ("tools/call", "toolscall"):
                tool_name = params.get("name")
                arguments = params.get("arguments", {})

                result = self._execute_tool(tool_name, arguments)

                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, indent=2)
                            }
                        ]
                    }
                }

            elif method_lower in ("listofferings", "list_offerings", "loffering"):
                # Respond to Cursor's ListOfferings UI request
                offerings = []
                for tool in self.tools:
                    offerings.append({
                        "name": tool.get("name"),
                        "displayName": tool.get("name"),
                        "description": tool.get("description")
                    })
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "offerings": offerings
                    }
                }

            elif method_lower == "ping":
                # Handle ping requests
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {}
                }

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }

        except Exception as e:
            logger.error(f"Error handling request: {e}")
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }

    def _execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool and return the result."""
        client = self._get_basecamp_client()
        if not client:
            # Check if it's specifically a token expiration issue
            if token_storage.is_token_expired():
                return {
                    "error": "OAuth token expired",
                    "message": "Your Basecamp OAuth token has expired. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
                }
            else:
                return {
                    "error": "Authentication required",
                    "message": "Please authenticate with Basecamp first. Visit http://localhost:8000 to log in."
                }

        try:
            if tool_name == "get_projects":
                projects = client.get_projects()
                return {
                    "status": "success",
                    "projects": projects,
                    "count": len(projects)
                }

            elif tool_name == "get_project":
                project_id = arguments.get("project_id")
                project = client.get_project(project_id)
                return {
                    "status": "success",
                    "project": project
                }

            elif tool_name == "get_todolists":
                project_id = arguments.get("project_id")
                todolists = client.get_todolists(project_id)
                return {
                    "status": "success",
                    "todolists": todolists,
                    "count": len(todolists)
                }

            elif tool_name == "get_todos":
                todolist_id = arguments.get("todolist_id")
                project_id = arguments.get("project_id")
                todos = client.get_todos(project_id, todolist_id)
                return {
                    "status": "success",
                    "todos": todos,
                    "count": len(todos)
                }

            elif tool_name == "search_basecamp":
                query = arguments.get("query")
                project_id = arguments.get("project_id")

                search = BasecampSearch(client=client)
                results = {}

                if project_id:
                    # Search within specific project
                    results["todolists"] = search.search_todolists(query, project_id)
                    results["todos"] = search.search_todos(query, project_id)
                else:
                    # Search across all projects
                    results["projects"] = search.search_projects(query)
                    results["todos"] = search.search_todos(query)
                    results["messages"] = search.search_messages(query)

                return {
                    "status": "success",
                    "query": query,
                    "results": results
                }

            elif tool_name == "global_search":
                query = arguments.get("query")
                search = BasecampSearch(client=client)
                results = search.global_search(query)
                return {
                    "status": "success",
                    "query": query,
                    "results": results
                }

            elif tool_name == "get_comments":
                recording_id = arguments.get("recording_id")
                project_id = arguments.get("project_id")
                comments = client.get_comments(project_id, recording_id)
                return {
                    "status": "success",
                    "comments": comments,
                    "count": len(comments)
                }

            elif tool_name == "get_campfire_lines":
                project_id = arguments.get("project_id")
                campfire_id = arguments.get("campfire_id")
                lines = client.get_campfire_lines(project_id, campfire_id)
                return {
                    "status": "success",
                    "campfire_lines": lines,
                    "count": len(lines)
                }
            elif tool_name == "get_daily_check_ins":
                project_id = arguments.get("project_id")
                page = arguments.get("page")
                answers = client.get_daily_check_ins(project_id, page=page)
                return {
                    "status": "success",
                    "campfire_lines": answers,
                    "count": len(answers)
                }
            elif tool_name == "get_question_answers":
                project_id = arguments.get("project_id")
                question_id = arguments.get("question_id")
                page = arguments.get("page")
                answers = client.get_question_answers(project_id, question_id, page=page)
                return {
                    "status": "success",
                    "campfire_lines": answers,
                    "count": len(answers)
                }
            
            else:
                return {
                    "error": "Unknown tool",
                    "message": f"Tool '{tool_name}' is not supported"
                }

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            # Check if it's a 401 error (token expired during API call)
            if "401" in str(e) and "expired" in str(e).lower():
                return {
                    "error": "OAuth token expired",
                    "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
                }
            return {
                "error": "Execution error",
                "message": str(e)
            }

    def run(self):
        """Run the MCP server, reading from stdin and writing to stdout."""
        logger.info("Starting MCP CLI server")

        for line in sys.stdin:
            try:
                line = line.strip()
                if not line:
                    continue

                request = json.loads(line)
                response = self.handle_request(request)

                # Write response to stdout (only if there's a response)
                if response is not None:
                    print(json.dumps(response), flush=True)

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON received: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                }
                print(json.dumps(error_response), flush=True)

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    }
                }
                print(json.dumps(error_response), flush=True)

if __name__ == "__main__":
    server = MCPServer()
    server.run()
