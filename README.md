# Basecamp MCP Server

[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-FastMCP-111827.svg)](https://modelcontextprotocol.io/)
[![Basecamp](https://img.shields.io/badge/Basecamp-3-1f8c4c.svg)](https://basecamp.com/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An MCP server for Basecamp 3. It lets MCP-capable clients such as Codex, Cursor, and Claude Desktop read and manage Basecamp projects through OAuth-authenticated Basecamp API calls.

The main server is [`basecamp_fastmcp.py`](basecamp_fastmcp.py). It uses the official `mcp.server.fastmcp` Python SDK and exposes 77 tools covering projects, todos, message boards, campfires, card tables, inbox forwards, documents, uploads, comments, events, webhooks, and search.

## What It Can Do

- Browse Basecamp projects and project details.
- Search across projects, todos, messages, campfire lines, comments, uploads, and schedules.
- Read and manage todolists, todos, todo groups, and completion state.
- Read and post message board messages, including categories.
- Read campfire lines.
- Read and create comments.
- Work with card tables, columns, cards, and card steps.
- Read inbox forwards and replies.
- Read daily check-ins and answers.
- Upload attachments and inspect uploads.
- Read and manage documents.
- List events and manage webhooks.
- Generate local MCP configuration for Codex, Cursor, and Claude Desktop.

## Requirements

- Python 3.10 or newer.
- A Basecamp 3 account.
- A Basecamp OAuth application from <https://launchpad.37signals.com/integrations>.
- A client that can run local MCP servers, such as Codex, Cursor, or Claude Desktop.

If your system Python is older, use `uv`; it can create a virtual environment with a newer Python version.

## Quick Start

Clone the repository and install dependencies:

```bash
git clone https://github.com/georgeantonopoulos/Basecamp-MCP-Server.git
cd Basecamp-MCP-Server

uv venv --python 3.12 venv
source venv/bin/activate
uv pip install -r requirements.txt
```

Or, if `python` already points to Python 3.10 or newer:

```bash
python setup.py
```

Create a `.env` file from the example and fill in your Basecamp OAuth details:

```bash
cp .env.example .env
```

Required values:

```bash
BASECAMP_CLIENT_ID=your-client-id
BASECAMP_CLIENT_SECRET=your-client-secret
BASECAMP_ACCOUNT_ID=your-account-id
USER_AGENT="Your App Name (your@email.com)"
```

Authenticate with Basecamp:

```bash
python oauth_app.py
```

Open <http://localhost:8000> and complete the OAuth flow. The token is stored locally in `oauth_tokens.json` by default.

## Configure Your MCP Client

### Codex

```bash
python generate_codex_config.py
codex mcp get basecamp
```

Useful options:

```bash
python generate_codex_config.py --dry-run
python generate_codex_config.py --legacy
```

The script writes a `basecamp` server entry to `~/.codex/config.toml` and points it at this checkout's virtual environment and [`basecamp_fastmcp.py`](basecamp_fastmcp.py).

### Cursor

```bash
python generate_cursor_config.py
```

Then restart Cursor and check Settings -> MCP. The server should appear as `basecamp`.

### Claude Desktop

```bash
python generate_claude_desktop_config.py
```

Then fully quit and reopen Claude Desktop. The generated config is written to:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `~/AppData/Roaming/Claude/claude_desktop_config.json`
- Linux: `~/.config/claude-desktop/claude_desktop_config.json`

## Verify The Server

Run the FastMCP server through stdio and ask for its tool list:

```bash
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | python basecamp_fastmcp.py
```

Run the automated tests:

```bash
python -m pytest tests/ -v
```

## Available Tools

The FastMCP server exposes 77 tools.

### Projects And Search

- `get_projects`
- `get_project`
- `search_basecamp`
- `global_search`

### Todos

- `get_todolists`
- `get_todolist`
- `create_todolist`
- `update_todolist`
- `trash_todolist`
- `get_todos`
- `get_todo`
- `create_todo`
- `update_todo`
- `delete_todo`
- `archive_todo`
- `complete_todo`
- `uncomplete_todo`
- `reposition_todo`
- `get_todolist_groups`
- `create_todolist_group`
- `reposition_todolist_group`

### Messages, Campfires, And Check-Ins

- `get_message_board`
- `get_messages`
- `get_message`
- `get_message_categories`
- `create_message`
- `get_campfire_lines`
- `get_daily_check_ins`
- `get_question_answers`

### Comments

- `get_comments`
- `create_comment`

### Card Tables

- `get_card_tables`
- `get_card_table`
- `get_columns`
- `get_column`
- `create_column`
- `update_column`
- `move_column`
- `update_column_color`
- `put_column_on_hold`
- `remove_column_hold`
- `watch_column`
- `unwatch_column`
- `get_cards`
- `get_card`
- `create_card`
- `update_card`
- `move_card`
- `complete_card`
- `uncomplete_card`
- `get_card_steps`
- `create_card_step`
- `get_card_step`
- `update_card_step`
- `delete_card_step`
- `complete_card_step`
- `uncomplete_card_step`

### Inbox Forwards

- `get_inbox`
- `get_forwards`
- `get_forward`
- `get_inbox_replies`
- `get_inbox_reply`
- `trash_forward`

### Documents, Uploads, Attachments, Events, And Webhooks

- `create_attachment`
- `get_uploads`
- `get_upload`
- `download_upload` — download a vault Upload recording (Docs & Files) and
  return its bytes as MCP content (``ImageContent`` for image MIME types,
  ``EmbeddedResource`` / ``BlobResourceContents`` otherwise). The MCP host
  forwards the blob to the model, so PDFs, images, and documents are read
  natively without an out-of-band fetch.
- `download_attachment` — download an inline comment/message attachment by its
  ``content_attachments[].download_url`` and return it as MCP content. Use this
  for files embedded into a comment or message body. Inline attachments are
  ``Attachment`` objects with their own IDs and cannot be resolved through
  ``/uploads/{id}`` — that endpoint returns 404. For files that are their own
  Upload recording in a vault, use ``download_upload`` instead.
- `get_documents`
- `get_document`
- `create_document`
- `update_document`
- `trash_document`
- `get_events`
- `get_webhooks`
- `create_webhook`
- `delete_webhook`

## Example Prompts

- "Show me all my Basecamp projects."
- "Search Basecamp for deadline."
- "Get the todolists for project 123456."
- "Create a todo called Review PR in todolist 987654."
- "Show me the message board categories for project 123456."
- "Post an Announcement to the project message board."
- "Show me the card table columns for project 123456."
- "Move this card to the Done column."
- "List the latest uploads in this project's vault."
- "Download the screenshot attached to that comment so you can read it."

## Architecture

- [`basecamp_fastmcp.py`](basecamp_fastmcp.py): FastMCP stdio server used by MCP clients.
- [`basecamp_client.py`](basecamp_client.py): Synchronous Basecamp 3 API client.
- [`search_utils.py`](search_utils.py): Higher-level search helpers across Basecamp resources.
- [`oauth_app.py`](oauth_app.py): Local Flask OAuth flow for Basecamp authentication.
- [`auth_manager.py`](auth_manager.py): OAuth refresh helper used before API calls.
- [`token_storage.py`](token_storage.py): Local OAuth token storage.
- [`generate_codex_config.py`](generate_codex_config.py): Codex MCP configuration generator.
- [`generate_cursor_config.py`](generate_cursor_config.py): Cursor MCP configuration generator.
- [`generate_claude_desktop_config.py`](generate_claude_desktop_config.py): Claude Desktop configuration generator.
- [`mcp_server_cli.py`](mcp_server_cli.py): Legacy JSON-RPC server kept for compatibility and tests.

## Authentication And Token Storage

The recommended path is OAuth 2.0:

1. Create a Basecamp OAuth app.
2. Put the client ID, client secret, account ID, redirect URI, and user agent in `.env`.
3. Run `python oauth_app.py`.
4. Complete the browser flow at <http://localhost:8000>.

By default, OAuth tokens are stored in `<project>/oauth_tokens.json`. For containers, read-only checkouts, or mounted token volumes, set `BASECAMP_MCP_TOKEN_FILE`:

```bash
export BASECAMP_MCP_TOKEN_FILE=/var/lib/basecamp-mcp/oauth_tokens.json
```

Both the OAuth app and the MCP server read the same variable. `token_storage.py` expands `~` and environment variables in this path, creates the parent directory if needed, and attempts to set the token file permissions to `0o600` when writing. Parent directory permissions are still your responsibility.

## Troubleshooting

If tools do not appear in your MCP client:

1. Confirm the virtual environment exists and has the MCP SDK:

   ```bash
   ./venv/bin/python -c "import mcp; print('MCP available')"
   ```

2. Confirm `.env` contains `BASECAMP_ACCOUNT_ID`.
3. Re-run the relevant config generator.
4. Fully quit and restart your MCP client.

If authentication fails:

```bash
python oauth_app.py
```

Then open <http://localhost:8000> and complete the Basecamp OAuth flow again.

For Claude Desktop on macOS, MCP logs are usually under:

```bash
~/Library/Logs/Claude/
```

## Security Notes

- Do not commit `.env` or `oauth_tokens.json`.
- Use a descriptive `USER_AGENT` that includes contact information, as Basecamp expects API clients to identify themselves.
- Keep token files on local or appropriately permissioned storage.
- This server is designed for local MCP client use. Review the code and deployment model before exposing it on a network.

## License

MIT. See [`LICENSE`](LICENSE).

## Star History

<a href="https://www.star-history.com/#georgeantonopoulos/Basecamp-MCP-Server&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=georgeantonopoulos/Basecamp-MCP-Server&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=georgeantonopoulos/Basecamp-MCP-Server&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=georgeantonopoulos/Basecamp-MCP-Server&type=Date" />
  </picture>
</a>
