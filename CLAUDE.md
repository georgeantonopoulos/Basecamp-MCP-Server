# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a **Basecamp 3 MCP (Model Context Protocol) Server** that allows AI assistants (Cursor, Claude Desktop) to interact with Basecamp directly. It uses OAuth 2.0 for authentication and provides 74 tools for Basecamp operations.

## Development Commands

```bash
# Setup (one-time) - requires Python 3.10+
# Option 1: Using uv (recommended - auto-downloads Python 3.12)
uv venv --python 3.12 venv && source venv/bin/activate && uv pip install -r requirements.txt && uv pip install mcp

# Option 2: Using pip (if Python 3.10+ already installed)
python setup.py                      # Creates venv, installs deps, tests server

# OAuth Authentication
python oauth_app.py                  # Start OAuth server at http://localhost:8000

# Run the MCP server (for testing)
./venv/bin/python basecamp_fastmcp.py    # FastMCP server (recommended)
./venv/bin/python mcp_server_cli.py      # Legacy CLI server

# Test the server manually
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python basecamp_fastmcp.py

# Run tests
python -m pytest tests/ -v           # All tests
python -m pytest tests/test_cli_server.py -v  # Specific test file

# Generate client configs
python generate_cursor_config.py           # For Cursor IDE
python generate_claude_desktop_config.py   # For Claude Desktop
```

## Architecture

### Core Files

| File | Purpose |
| ------ | --------- |
| `basecamp_fastmcp.py` | **Main MCP server** using official Anthropic FastMCP framework (74 tools) |
| `mcp_server_cli.py` | Legacy JSON-RPC server (same tools, custom implementation) |
| `basecamp_client.py` | Basecamp 3 API client - all HTTP methods and endpoints |
| `basecamp_oauth.py` | OAuth 2.0 client for 37signals Launchpad |
| `auth_manager.py` | Automatic token refresh before API calls |
| `token_storage.py` | Thread-safe OAuth token persistence (`oauth_tokens.json`) |
| `search_utils.py` | Cross-project search functionality |
| `oauth_app.py` | Flask app for OAuth flow (browser-based login) |

### Data Flow

```
MCP Client (Cursor/Claude)
    ↓ JSON-RPC via stdio
basecamp_fastmcp.py (MCP Server)
    ↓ calls
auth_manager.ensure_authenticated() → token_storage → basecamp_oauth.refresh_token()
    ↓ if valid
basecamp_client.py (API calls)
    ↓ HTTP requests
Basecamp 3 API (https://3.basecampapi.com/{account_id})
```

### Authentication Flow

1. User runs `python oauth_app.py` and visits `http://localhost:8000`
2. Redirected to 37signals for authorization
3. Callback stores tokens in `oauth_tokens.json` (600 permissions)
4. MCP server uses `auth_manager.ensure_authenticated()` to auto-refresh expired tokens

### Tool Categories (74 total)

- **Projects**: `get_projects`, `get_project`
- **Todos**: `get_todolists`, `get_todolist`, `create_todolist`, `update_todolist`, `trash_todolist`, `get_todos`, `get_todo`, `create_todo`, `update_todo`, `delete_todo`, `complete_todo`, `uncomplete_todo`, `reposition_todo`, `archive_todo`
- **Todo List Groups**: `get_todolist_groups`, `get_todolist_group`, `create_todolist_group`, `reposition_todolist_group`
- **Card Tables (Kanban)**: `get_card_table`, `get_columns`, `get_cards`, `create_card`, `move_card`, `complete_card`, etc.
- **Card Steps**: `get_card_steps`, `create_card_step`, `complete_card_step`, etc.
- **Comments**: `get_comments`, `create_comment`
- **Messages**: `get_message_board`, `get_messages`, `get_message`
- **Campfire (Chat)**: `get_campfire_lines`
- **Documents**: `get_documents`, `create_document`, `update_document`, `trash_document`
- **Inbox (Email Forwards)**: `get_inbox`, `get_forwards`, `get_forward`, `get_inbox_replies`, `get_inbox_reply`, `trash_forward`
- **Search**: `search_basecamp`, `global_search`
- **Webhooks**: `get_webhooks`, `create_webhook`, `delete_webhook`
- **Other**: `get_daily_check_ins`, `get_question_answers`, `get_events`, `create_attachment`, `get_uploads`

## Key Patterns

### Adding New MCP Tools (FastMCP)

```python
# In basecamp_fastmcp.py
@mcp.tool()
async def new_tool_name(project_id: str, other_param: Optional[str] = None) -> Dict[str, Any]:
    """Tool description shown to AI.

    Args:
        project_id: The project ID
        other_param: Optional description
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        result = await _run_sync(client.some_method, project_id, other_param)
        return {"status": "success", "data": result}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"error": "Execution error", "message": str(e)}
```

### Adding Basecamp API Methods

```python
# In basecamp_client.py
def new_api_method(self, project_id, resource_id):
    """Method description."""
    endpoint = f'buckets/{project_id}/resource/{resource_id}.json'
    response = self.get(endpoint)  # or .post(), .put(), .delete(), .patch()
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Failed: {response.status_code} - {response.text}")
```

### Pagination Handling

Basecamp paginates list endpoints (~15 items/page). See `get_todos()` in `basecamp_client.py` for the pattern using `Link` header.

## Environment Configuration

Required in `.env`:

``` bash
BASECAMP_CLIENT_ID=your_client_id
BASECAMP_CLIENT_SECRET=your_client_secret
BASECAMP_ACCOUNT_ID=your_account_id
BASECAMP_REDIRECT_URI=http://localhost:8000/auth/callback
USER_AGENT="Your App Name (your@email.com)"
```

The account ID can be found in your Basecamp URL: `https://3.basecamp.com/{account_id}/projects`

## Troubleshooting

- **Token expired**: Visit `http://localhost:8000` to re-authenticate (auto-refresh usually handles this)
- **Missing tools in Cursor/Claude**: Restart the client completely after config changes
- **Logs**: Check `basecamp_fastmcp.log` or `mcp_cli_server.log` for errors
- **Test token validity**: `python auth_manager.py` to force refresh check

## Reference

- API docs in `reference/bc3-api/sections/` - useful when implementing new endpoints
- Local queries/scripts go in `local_queries/` (git-ignored)
