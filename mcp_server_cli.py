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
                "name": "create_todo",
                "description": "Create a new todo item in a todo list",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "todolist_id": {"type": "string", "description": "The todo list ID"},
                        "content": {"type": "string", "description": "The todo item's text (required)"},
                        "description": {"type": "string", "description": "HTML description of the todo"},
                        "assignee_ids": {"type": "array", "items": {"type": "string"}, "description": "List of person IDs to assign"},
                        "completion_subscriber_ids": {"type": "array", "items": {"type": "string"}, "description": "List of person IDs to notify on completion"},
                        "notify": {"type": "boolean", "description": "Whether to notify assignees"},
                        "due_on": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
                        "starts_on": {"type": "string", "description": "Start date in YYYY-MM-DD format"}
                    },
                    "required": ["project_id", "todolist_id", "content"]
                }
            },
            {
                "name": "update_todo",
                "description": "Update an existing todo item",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "todo_id": {"type": "string", "description": "The todo ID"},
                        "content": {"type": "string", "description": "The todo item's text"},
                        "description": {"type": "string", "description": "HTML description of the todo"},
                        "assignee_ids": {"type": "array", "items": {"type": "string"}, "description": "List of person IDs to assign"},
                        "completion_subscriber_ids": {"type": "array", "items": {"type": "string"}, "description": "List of person IDs to notify on completion"},
                        "notify": {"type": "boolean", "description": "Whether to notify assignees"},
                        "due_on": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
                        "starts_on": {"type": "string", "description": "Start date in YYYY-MM-DD format"}
                    },
                    "required": ["project_id", "todo_id"]
                }
            },
            {
                "name": "delete_todo",
                "description": "Delete a todo item",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "todo_id": {"type": "string", "description": "The todo ID"}
                    },
                    "required": ["project_id", "todo_id"]
                }
            },
            {
                "name": "complete_todo",
                "description": "Mark a todo item as complete",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "todo_id": {"type": "string", "description": "The todo ID"}
                    },
                    "required": ["project_id", "todo_id"]
                }
            },
            {
                "name": "uncomplete_todo",
                "description": "Mark a todo item as incomplete",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "todo_id": {"type": "string", "description": "The todo ID"}
                    },
                    "required": ["project_id", "todo_id"]
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
            },
            # Card Table tools
            {
                "name": "get_card_tables",
                "description": "Get all card tables for a project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "get_card_table",
                "description": "Get the card table details for a project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "get_columns",
                "description": "Get all columns in a card table",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_table_id": {"type": "string", "description": "The card table ID"}
                    },
                    "required": ["project_id", "card_table_id"]
                }
            },
            {
                "name": "get_column",
                "description": "Get details for a specific column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"}
                    },
                    "required": ["project_id", "column_id"]
                }
            },
            {
                "name": "create_column",
                "description": "Create a new column in a card table",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_table_id": {"type": "string", "description": "The card table ID"},
                        "title": {"type": "string", "description": "The column title"}
                    },
                    "required": ["project_id", "card_table_id", "title"]
                }
            },
            {
                "name": "update_column",
                "description": "Update a column title",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"},
                        "title": {"type": "string", "description": "The new column title"}
                    },
                    "required": ["project_id", "column_id", "title"]
                }
            },
            {
                "name": "move_column",
                "description": "Move a column to a new position",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_table_id": {"type": "string", "description": "The card table ID"},
                        "column_id": {"type": "string", "description": "The column ID"},
                        "position": {"type": "integer", "description": "The new 1-based position"}
                    },
                    "required": ["project_id", "card_table_id", "column_id", "position"]
                }
            },
            {
                "name": "update_column_color",
                "description": "Update a column color",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"},
                        "color": {"type": "string", "description": "The hex color code (e.g., #FF0000)"}
                    },
                    "required": ["project_id", "column_id", "color"]
                }
            },
            {
                "name": "put_column_on_hold",
                "description": "Put a column on hold (freeze work)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"}
                    },
                    "required": ["project_id", "column_id"]
                }
            },
            {
                "name": "remove_column_hold",
                "description": "Remove hold from a column (unfreeze work)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"}
                    },
                    "required": ["project_id", "column_id"]
                }
            },
            {
                "name": "watch_column",
                "description": "Subscribe to notifications for changes in a column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"}
                    },
                    "required": ["project_id", "column_id"]
                }
            },
            {
                "name": "unwatch_column",
                "description": "Unsubscribe from notifications for a column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"}
                    },
                    "required": ["project_id", "column_id"]
                }
            },
            {
                "name": "get_cards",
                "description": "Get all cards in a column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"}
                    },
                    "required": ["project_id", "column_id"]
                }
            },
            {
                "name": "get_card",
                "description": "Get details for a specific card",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_id": {"type": "string", "description": "The card ID"}
                    },
                    "required": ["project_id", "card_id"]
                }
            },
            {
                "name": "create_card",
                "description": "Create a new card in a column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "column_id": {"type": "string", "description": "The column ID"},
                        "title": {"type": "string", "description": "The card title"},
                        "content": {"type": "string", "description": "Optional card content/description"},
                        "due_on": {"type": "string", "description": "Optional due date (ISO 8601 format)"},
                        "notify": {"type": "boolean", "description": "Whether to notify assignees (default: false)"}
                    },
                    "required": ["project_id", "column_id", "title"]
                }
            },
            {
                "name": "update_card",
                "description": "Update a card",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_id": {"type": "string", "description": "The card ID"},
                        "title": {"type": "string", "description": "The new card title"},
                        "content": {"type": "string", "description": "The new card content/description"},
                        "due_on": {"type": "string", "description": "Due date (ISO 8601 format)"},
                        "assignee_ids": {"type": "array", "items": {"type": "string"}, "description": "Array of person IDs to assign to the card"}
                    },
                    "required": ["project_id", "card_id"]
                }
            },
            {
                "name": "move_card",
                "description": "Move a card to a new column",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_id": {"type": "string", "description": "The card ID"},
                        "column_id": {"type": "string", "description": "The destination column ID"}
                    },
                    "required": ["project_id", "card_id", "column_id"]
                }
            },
            {
                "name": "complete_card",
                "description": "Mark a card as complete",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_id": {"type": "string", "description": "The card ID"}
                    },
                    "required": ["project_id", "card_id"]
                }
            },
            {
                "name": "uncomplete_card",
                "description": "Mark a card as incomplete",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_id": {"type": "string", "description": "The card ID"}
                    },
                    "required": ["project_id", "card_id"]
                }
            },
            {
                "name": "get_card_steps",
                "description": "Get all steps (sub-tasks) for a card",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_id": {"type": "string", "description": "The card ID"}
                    },
                    "required": ["project_id", "card_id"]
                }
            },
            {
                "name": "create_card_step",
                "description": "Create a new step (sub-task) for a card",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "card_id": {"type": "string", "description": "The card ID"},
                        "title": {"type": "string", "description": "The step title"},
                        "due_on": {"type": "string", "description": "Optional due date (ISO 8601 format)"},
                        "assignee_ids": {"type": "array", "items": {"type": "string"}, "description": "Array of person IDs to assign to the step"}
                    },
                    "required": ["project_id", "card_id", "title"]
                }
            },
            {
                "name": "get_card_step",
                "description": "Get details for a specific card step",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "step_id": {"type": "string", "description": "The step ID"}
                    },
                    "required": ["project_id", "step_id"]
                }
            },
            {
                "name": "update_card_step",
                "description": "Update a card step",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "step_id": {"type": "string", "description": "The step ID"},
                        "title": {"type": "string", "description": "The step title"},
                        "due_on": {"type": "string", "description": "Due date (ISO 8601 format)"},
                        "assignee_ids": {"type": "array", "items": {"type": "string"}, "description": "Array of person IDs to assign to the step"}
                    },
                    "required": ["project_id", "step_id"]
                }
            },
            {
                "name": "delete_card_step",
                "description": "Delete a card step",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "step_id": {"type": "string", "description": "The step ID"}
                    },
                    "required": ["project_id", "step_id"]
                }
            },
            {
                "name": "complete_card_step",
                "description": "Mark a card step as complete",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "step_id": {"type": "string", "description": "The step ID"}
                    },
                    "required": ["project_id", "step_id"]
                }
            },
            {
                "name": "uncomplete_card_step",
                "description": "Mark a card step as incomplete",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The project ID"},
                        "step_id": {"type": "string", "description": "The step ID"}
                    },
                    "required": ["project_id", "step_id"]
                }
            },
            {
                "name": "create_attachment",
                "description": "Upload a file as an attachment",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Local path to file"},
                        "name": {"type": "string", "description": "Filename for Basecamp"},
                        "content_type": {"type": "string", "description": "MIME type"}
                    },
                    "required": ["file_path", "name"]
                }
            },
            {
                "name": "get_events",
                "description": "Get events for a recording",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "recording_id": {"type": "string", "description": "Recording ID"}
                    },
                    "required": ["project_id", "recording_id"]
                }
            },
            {
                "name": "get_webhooks",
                "description": "List webhooks for a project",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "create_webhook",
                "description": "Create a webhook",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "payload_url": {"type": "string", "description": "Payload URL"},
                        "types": {"type": "array", "items": {"type": "string"}, "description": "Event types"}
                    },
                    "required": ["project_id", "payload_url"]
                }
            },
            {
                "name": "delete_webhook",
                "description": "Delete a webhook",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "webhook_id": {"type": "string", "description": "Webhook ID"}
                    },
                    "required": ["project_id", "webhook_id"]
                }
            },
            {
                "name": "get_documents",
                "description": "List documents in a vault",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "vault_id": {"type": "string", "description": "Vault ID"}
                    },
                    "required": ["project_id", "vault_id"]
                }
            },
            {
                "name": "get_document",
                "description": "Get a single document",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "document_id": {"type": "string", "description": "Document ID"}
                    },
                    "required": ["project_id", "document_id"]
                }
            },
            {
                "name": "create_document",
                "description": "Create a document in a vault",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "vault_id": {"type": "string", "description": "Vault ID"},
                        "title": {"type": "string", "description": "Document title"},
                        "content": {"type": "string", "description": "Document HTML content"}
                    },
                    "required": ["project_id", "vault_id", "title", "content"]
                }
            },
            {
                "name": "update_document",
                "description": "Update a document",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "document_id": {"type": "string", "description": "Document ID"},
                        "title": {"type": "string", "description": "New title"},
                        "content": {"type": "string", "description": "New HTML content"}
                    },
                    "required": ["project_id", "document_id"]
                }
            },
            {
                "name": "trash_document",
                "description": "Move a document to trash",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "Project ID"},
                        "document_id": {"type": "string", "description": "Document ID"}
                    },
                    "required": ["project_id", "document_id"]
                }
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

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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

            elif tool_name == "create_todo":
                project_id = arguments.get("project_id")
                todolist_id = arguments.get("todolist_id")
                content = arguments.get("content")
                description = arguments.get("description")
                assignee_ids = arguments.get("assignee_ids")
                completion_subscriber_ids = arguments.get("completion_subscriber_ids")
                notify_arg = arguments.get("notify", False)
                if isinstance(notify_arg, str):
                    notify = notify_arg.strip().lower() in ("1", "true", "yes", "on")
                else:
                    notify = bool(notify_arg)
                due_on = arguments.get("due_on")
                starts_on = arguments.get("starts_on")
                
                todo = client.create_todo(
                    project_id, todolist_id, content,
                    description=description,
                    assignee_ids=assignee_ids,
                    completion_subscriber_ids=completion_subscriber_ids,
                    notify=notify,
                    due_on=due_on,
                    starts_on=starts_on
                )
                return {
                    "status": "success",
                    "todo": todo,
                    "message": f"Todo '{content}' created successfully"
                }

            elif tool_name == "update_todo":
                project_id = arguments.get("project_id")
                todo_id = arguments.get("todo_id")
                content = arguments.get("content")
                description = arguments.get("description")
                assignee_ids = arguments.get("assignee_ids")
                completion_subscriber_ids = arguments.get("completion_subscriber_ids")
                due_on = arguments.get("due_on")
                starts_on = arguments.get("starts_on")
                notify = arguments.get("notify")
                
                todo = client.update_todo(
                    project_id, todo_id,
                    content=content,
                    description=description,
                    assignee_ids=assignee_ids,
                    completion_subscriber_ids=completion_subscriber_ids,
                    notify=notify,
                    due_on=due_on,
                    starts_on=starts_on
                )
                return {
                    "status": "success",
                    "todo": todo,
                    "message": "Todo updated successfully"
                }

            elif tool_name == "delete_todo":
                project_id = arguments.get("project_id")
                todo_id = arguments.get("todo_id")
                client.delete_todo(project_id, todo_id)
                return {
                    "status": "success",
                    "message": "Todo deleted successfully"
                }

            elif tool_name == "complete_todo":
                project_id = arguments.get("project_id")
                todo_id = arguments.get("todo_id")
                completion = client.complete_todo(project_id, todo_id)
                return {
                    "status": "success",
                    "completion": completion,
                    "message": "Todo marked as complete"
                }

            elif tool_name == "uncomplete_todo":
                project_id = arguments.get("project_id")
                todo_id = arguments.get("todo_id")
                client.uncomplete_todo(project_id, todo_id)
                return {
                    "status": "success",
                    "message": "Todo marked as incomplete"
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
                page = arguments.get("page", 1)
                if page is not None and not isinstance(page, int):
                    page = 1
                answers = client.get_daily_check_ins(project_id, page=page)
                return {
                    "status": "success",
                    "campfire_lines": answers,
                    "count": len(answers)
                }
            elif tool_name == "get_question_answers":
                project_id = arguments.get("project_id")
                question_id = arguments.get("question_id")
                page = arguments.get("page", 1)
                if page is not None and not isinstance(page, int):
                    page = 1
                answers = client.get_question_answers(project_id, question_id, page=page)
                return {
                    "status": "success",
                    "campfire_lines": answers,
                    "count": len(answers)
                }
            
            # Card Table tools implementation
            elif tool_name == "get_card_tables":
                project_id = arguments.get("project_id")
                card_tables = client.get_card_tables(project_id)
                return {
                    "status": "success",
                    "card_tables": card_tables,
                    "count": len(card_tables)
                }

            elif tool_name == "get_card_table":
                project_id = arguments.get("project_id")
                try:
                    card_table = client.get_card_table(project_id)
                    card_table_details = client.get_card_table_details(project_id, card_table['id'])
                    return {
                        "status": "success",
                        "card_table": card_table_details
                    }
                except Exception as e:
                    error_msg = str(e)
                    return {
                        "status": "error",
                        "message": f"Error getting card table: {error_msg}",
                        "debug": error_msg
                    }

            elif tool_name == "get_columns":
                project_id = arguments.get("project_id")
                card_table_id = arguments.get("card_table_id")
                columns = client.get_columns(project_id, card_table_id)
                return {
                    "status": "success",
                    "columns": columns,
                    "count": len(columns)
                }

            elif tool_name == "get_column":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                column = client.get_column(project_id, column_id)
                return {
                    "status": "success",
                    "column": column
                }

            elif tool_name == "create_column":
                project_id = arguments.get("project_id")
                card_table_id = arguments.get("card_table_id")
                title = arguments.get("title")
                column = client.create_column(project_id, card_table_id, title)
                return {
                    "status": "success",
                    "column": column,
                    "message": f"Column '{title}' created successfully"
                }

            elif tool_name == "update_column":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                title = arguments.get("title")
                column = client.update_column(project_id, column_id, title)
                return {
                    "status": "success",
                    "column": column,
                    "message": "Column updated successfully"
                }

            elif tool_name == "move_column":
                project_id = arguments.get("project_id")
                card_table_id = arguments.get("card_table_id")
                column_id = arguments.get("column_id")
                position = arguments.get("position")
                client.move_column(project_id, column_id, position, card_table_id)
                return {
                    "status": "success",
                    "message": f"Column moved to position {position}"
                }

            elif tool_name == "update_column_color":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                color = arguments.get("color")
                column = client.update_column_color(project_id, column_id, color)
                return {
                    "status": "success",
                    "column": column,
                    "message": f"Column color updated to {color}"
                }

            elif tool_name == "put_column_on_hold":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                client.put_column_on_hold(project_id, column_id)
                return {
                    "status": "success",
                    "message": "Column put on hold"
                }

            elif tool_name == "remove_column_hold":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                client.remove_column_hold(project_id, column_id)
                return {
                    "status": "success",
                    "message": "Column hold removed"
                }

            elif tool_name == "watch_column":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                client.watch_column(project_id, column_id)
                return {
                    "status": "success",
                    "message": "Column notifications enabled"
                }

            elif tool_name == "unwatch_column":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                client.unwatch_column(project_id, column_id)
                return {
                    "status": "success",
                    "message": "Column notifications disabled"
                }

            elif tool_name == "get_cards":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                cards = client.get_cards(project_id, column_id)
                return {
                    "status": "success",
                    "cards": cards,
                    "count": len(cards)
                }

            elif tool_name == "get_card":
                project_id = arguments.get("project_id")
                card_id = arguments.get("card_id")
                card = client.get_card(project_id, card_id)
                return {
                    "status": "success",
                    "card": card
                }

            elif tool_name == "create_card":
                project_id = arguments.get("project_id")
                column_id = arguments.get("column_id")
                title = arguments.get("title")
                content = arguments.get("content")
                due_on = arguments.get("due_on")
                notify = bool(arguments.get("notify", False))
                card = client.create_card(project_id, column_id, title, content, due_on, notify)
                return {
                    "status": "success",
                    "card": card,
                    "message": f"Card '{title}' created successfully"
                }

            elif tool_name == "update_card":
                project_id = arguments.get("project_id")
                card_id = arguments.get("card_id")
                title = arguments.get("title")
                content = arguments.get("content")
                due_on = arguments.get("due_on")
                assignee_ids = arguments.get("assignee_ids")
                card = client.update_card(project_id, card_id, title, content, due_on, assignee_ids)
                return {
                    "status": "success",
                    "card": card,
                    "message": "Card updated successfully"
                }

            elif tool_name == "move_card":
                project_id = arguments.get("project_id")
                card_id = arguments.get("card_id")
                column_id = arguments.get("column_id")
                client.move_card(project_id, card_id, column_id)
                message = "Card moved"
                if column_id:
                    message = f"Card moved to column {column_id}"
                return {
                    "status": "success",
                    "message": message
                }
            
            elif tool_name == "complete_card":
                project_id = arguments.get("project_id")
                card_id = arguments.get("card_id")
                client.complete_card(project_id, card_id)
                return {
                    "status": "success",
                    "message": "Card marked as complete"
                }

            elif tool_name == "uncomplete_card":
                project_id = arguments.get("project_id")
                card_id = arguments.get("card_id")
                client.uncomplete_card(project_id, card_id)
                return {
                    "status": "success",
                    "message": "Card marked as incomplete"
                }

            elif tool_name == "get_card_steps":
                project_id = arguments.get("project_id")
                card_id = arguments.get("card_id")
                steps = client.get_card_steps(project_id, card_id)
                return {
                    "status": "success",
                    "steps": steps,
                    "count": len(steps)
                }

            elif tool_name == "create_card_step":
                project_id = arguments.get("project_id")
                card_id = arguments.get("card_id")
                title = arguments.get("title")
                due_on = arguments.get("due_on")
                assignee_ids = arguments.get("assignee_ids")
                step = client.create_card_step(project_id, card_id, title, due_on, assignee_ids)
                return {
                    "status": "success",
                    "step": step,
                    "message": f"Step '{title}' created successfully"
                }

            elif tool_name == "get_card_step":
                project_id = arguments.get("project_id")
                step_id = arguments.get("step_id")
                step = client.get_card_step(project_id, step_id)
                return {
                    "status": "success",
                    "step": step
                }

            elif tool_name == "update_card_step":
                project_id = arguments.get("project_id")
                step_id = arguments.get("step_id")
                title = arguments.get("title")
                due_on = arguments.get("due_on")
                assignee_ids = arguments.get("assignee_ids")
                step = client.update_card_step(project_id, step_id, title, due_on, assignee_ids)
                return {
                    "status": "success",
                    "step": step,
                    "message": f"Step '{title}' updated successfully"
                }

            elif tool_name == "delete_card_step":
                project_id = arguments.get("project_id")
                step_id = arguments.get("step_id")
                client.delete_card_step(project_id, step_id)
                return {
                    "status": "success",
                    "message": "Step deleted successfully"
                }

            elif tool_name == "complete_card_step":
                project_id = arguments.get("project_id")
                step_id = arguments.get("step_id")
                client.complete_card_step(project_id, step_id)
                return {
                    "status": "success",
                    "message": "Step marked as complete"
                }

            elif tool_name == "uncomplete_card_step":
                project_id = arguments.get("project_id")
                step_id = arguments.get("step_id")
                client.uncomplete_card_step(project_id, step_id)
                return {
                    "status": "success",
                    "message": "Step marked as incomplete"
                }

            elif tool_name == "create_attachment":
                file_path = arguments.get("file_path")
                name = arguments.get("name")
                content_type = arguments.get("content_type", "application/octet-stream")
                result = client.create_attachment(file_path, name, content_type)
                return {
                    "status": "success",
                    "attachment": result
                }

            elif tool_name == "get_events":
                project_id = arguments.get("project_id")
                recording_id = arguments.get("recording_id")
                events = client.get_events(project_id, recording_id)
                return {
                    "status": "success",
                    "events": events,
                    "count": len(events)
                }

            elif tool_name == "get_webhooks":
                project_id = arguments.get("project_id")
                hooks = client.get_webhooks(project_id)
                return {
                    "status": "success",
                    "webhooks": hooks,
                    "count": len(hooks)
                }

            elif tool_name == "create_webhook":
                project_id = arguments.get("project_id")
                payload_url = arguments.get("payload_url")
                types = arguments.get("types")
                hook = client.create_webhook(project_id, payload_url, types)
                return {
                    "status": "success",
                    "webhook": hook
                }

            elif tool_name == "delete_webhook":
                project_id = arguments.get("project_id")
                webhook_id = arguments.get("webhook_id")
                client.delete_webhook(project_id, webhook_id)
                return {
                    "status": "success",
                    "message": "Webhook deleted"
                }

            elif tool_name == "get_documents":
                project_id = arguments.get("project_id")
                vault_id = arguments.get("vault_id")
                docs = client.get_documents(project_id, vault_id)
                return {
                    "status": "success",
                    "documents": docs,
                    "count": len(docs)
                }

            elif tool_name == "get_document":
                project_id = arguments.get("project_id")
                document_id = arguments.get("document_id")
                doc = client.get_document(project_id, document_id)
                return {
                    "status": "success",
                    "document": doc
                }

            elif tool_name == "create_document":
                project_id = arguments.get("project_id")
                vault_id = arguments.get("vault_id")
                title = arguments.get("title")
                content = arguments.get("content")
                doc = client.create_document(project_id, vault_id, title, content)
                return {
                    "status": "success",
                    "document": doc
                }

            elif tool_name == "update_document":
                project_id = arguments.get("project_id")
                document_id = arguments.get("document_id")
                title = arguments.get("title")
                content = arguments.get("content")
                doc = client.update_document(project_id, document_id, title, content)
                return {
                    "status": "success",
                    "document": doc
                }

            elif tool_name == "trash_document":
                project_id = arguments.get("project_id")
                document_id = arguments.get("document_id")
                client.trash_document(project_id, document_id)
                return {
                    "status": "success",
                    "message": "Document trashed"
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
