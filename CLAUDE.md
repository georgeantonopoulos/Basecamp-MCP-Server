# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a **Basecamp 3 MCP (Model Context Protocol) Server** that allows AI assistants (Cursor, Claude Desktop) to interact with Basecamp directly. It uses OAuth 2.0 and provides category-based retrieval over 210 canonical Basecamp operations.

## Development Commands

```bash
# Setup (one-time) - requires Python 3.10+
# Option 1: Using uv (recommended - auto-downloads Python 3.12)
uv venv --python 3.12 venv && source venv/bin/activate && uv pip install -r requirements.txt

# Option 2: Using pip (if Python 3.10+ already installed)
python setup.py                      # Creates venv, installs deps, tests server

# OAuth Authentication
python oauth_app.py                  # Start OAuth server at http://localhost:8000

# Run the MCP server (for testing)
./venv/bin/python basecamp_retrieval_mcp.py # Retrieval-first server (recommended)
./venv/bin/python basecamp_fastmcp.py    # Full 210-tool FastMCP server
./venv/bin/python mcp_server_cli.py      # Legacy CLI server

# Test the server manually
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | python basecamp_retrieval_mcp.py

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
| `basecamp_retrieval_mcp.py` | **Recommended MCP server** exposing four retrieval and dispatch tools |
| `basecamp_tool_retrieval.py` | Categories, read/write classification, ranking, and schema projection |
| `basecamp_fastmcp.py` | Canonical FastMCP registry and optional full-catalog server (210 tools) |
| `mcp_server_cli.py` | Legacy JSON-RPC transport deriving catalog and dispatch from the FastMCP registry |
| `basecamp_client.py` | Basecamp 3 API client - all HTTP methods and endpoints |
| `basecamp_oauth.py` | OAuth 2.0 client for 37signals Launchpad |
| `auth_manager.py` | Automatic token refresh before API calls |
| `token_storage.py` | Thread-safe OAuth token persistence. Path defaults to `<project>/oauth_tokens.json`; override with `BASECAMP_MCP_TOKEN_FILE` env var |
| `search_utils.py` | Cross-project search functionality |
| `oauth_app.py` | Flask app for OAuth flow (browser-based login) |

### Data Flow

```
MCP Client (Cursor/Claude)
    ↓ JSON-RPC via stdio
basecamp_retrieval_mcp.py (discovery + read/write dispatch)
    ↓ validates and dispatches through
basecamp_fastmcp.py (210 canonical tool definitions)
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
3. Callback stores tokens in `oauth_tokens.json` (600 permissions — location configurable via `BASECAMP_MCP_TOKEN_FILE`)
4. MCP server uses `auth_manager.ensure_authenticated()` to auto-refresh expired tokens

### Tool Categories (210 total)

- **Projects**: `get_projects`, `get_project`, `create_project`, `update_project`, `trash_project`
- **Templates**: `get_templates`, `get_template`, `create_template`, `update_template`, `trash_template`, `create_project_from_template`, `get_project_construction`
- **Todos**: `get_todolists`, `get_todolist`, `create_todolist`, `update_todolist`, `trash_todolist`, `get_todos`, `get_todo`, `create_todo`, `update_todo`, `delete_todo`, `complete_todo`, `uncomplete_todo`, `reposition_todo`, `archive_todo`
- **Todo List Groups**: `get_todolist_groups`, `create_todolist_group`, `reposition_todolist_group`
- **Card Tables (Kanban)**: `get_card_table`, `get_columns`, `get_cards`, `create_card`, `move_card`, `complete_card`, etc.
- **Card Steps**: `get_card_steps`, `create_card_step`, `complete_card_step`, etc.
- **Comments**: `get_comments`, `create_comment`, `get_comment`, `update_comment`, `delete_comment`
- **Messages**: `get_message_board`, `get_messages`, `get_message`, `get_message_categories`, `create_message`, `update_message`, `pin_message`, `unpin_message`, `create_draft_message`
- **Message Categories**: `get_message_category`, `create_message_category`, `update_message_category`, `delete_message_category`
- **Campfire (Chat)**: `get_campfire_lines`, `get_campfires`, `get_campfire_line`, `create_campfire_line`, `delete_campfire_line`
- **Automatic Check-ins**: `get_daily_check_ins`, `get_questionnaire`, `get_questions`, `get_question`, `get_question_answers`, `get_question_answer`, `create_question`, `update_question`, `pause_question`, `resume_question`, `update_question_notification_settings`, `get_question_answerers`
- **People**: `get_people`, `get_project_people`, `update_project_people`, `get_pingable_people`, `get_person`, `get_my_profile`
- **Reports**: `get_assignable_people`, `get_person_assignments`, `get_my_assignments`, `get_completed_assignments`, `get_due_assignments`, `get_overdue_todos`, `get_upcoming_schedule`, `get_question_reminders`, `prioritize_assignment`, `deprioritize_assignment`, `reorder_priority`
- **Timesheets**: `get_timesheet_report`, `get_project_timesheet`, `get_recording_timesheet`, `get_timesheet_entry`, `create_timesheet_entry`, `update_timesheet_entry`, `delete_timesheet_entry`
- **Gauges**: `get_gauges`, `get_gauge_needles`, `get_gauge_needle`, `create_gauge_needle`, `update_gauge_needle`, `delete_gauge_needle`, `toggle_gauge`
- **Hill Charts**: `get_hill_chart`, `get_project_hill_chart`, `update_hill_chart_settings`
- **Account**: `get_account`, `update_account_name`, `update_account_logo`, `remove_account_logo`
- **Client Visibility**: `update_recording_visibility`
- **Upload Lifecycle**: `update_upload`, `get_upload_versions`, `create_upload_version`
- **Dock Tools**: `get_dock_tool`, `create_dock_tool`, `update_dock_tool`, `enable_dock_tool`, `reposition_dock_tool`, `disable_dock_tool`, `trash_dock_tool`
- **Account-wide**: `get_everything_messages`, `get_everything_comments`, `get_everything_checkins`, `get_everything_forwards`, `get_everything_files`, `get_everything_todos`, `get_everything_cards`
- **Timelines**: `get_timeline`, `get_project_timeline`, `get_person_timeline`
- **Lineup**: `get_lineup_markers`, `create_lineup_marker`, `update_lineup_marker`, `delete_lineup_marker`
- **Personal**: `get_my_bookmarks`, `get_bookmark_status`, `create_bookmark`, `delete_bookmark`, `get_my_drafts`, `get_my_note`, `update_my_note`, `get_calendar`, `update_calendar`
- **Notifications**: `get_notifications`, `get_bubble_ups`, `mark_notifications_read`
- **Subscriptions**: `get_subscription`, `subscribe_to_recording`, `unsubscribe_from_recording`, `update_subscription`
- **Recordings**: `get_recordings`, `trash_recording`, `archive_recording`, `restore_recording`
- **Schedules**: `get_schedule`, `get_schedule_entries`, `get_schedule_entry`, `get_schedule_entry_occurrence`, `create_schedule_entry`, `update_schedule_entry`
- **Documents**: `get_documents`, `create_document`, `create_draft_document`, `update_document`, `trash_document`
- **Inbox (Email Forwards)**: `get_inbox`, `get_forwards`, `get_forward`, `get_inbox_replies`, `get_inbox_reply`, `trash_forward`
- **Search**: `search_basecamp`, `global_search`, `get_search_metadata`, `search_recordings`
- **Webhooks**: `get_webhooks`, `get_webhook`, `create_webhook`, `update_webhook`, `delete_webhook`
- **Other**: `get_events`, `create_attachment`, `get_uploads`

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
