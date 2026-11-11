# Basecamp MCP Server

[![PyPI](https://img.shields.io/pypi/v/basecamp-mcp-server.svg)](https://pypi.org/project/basecamp-mcp-server/)
[![Tests](https://github.com/georgeantonopoulos/Basecamp-MCP-Server/actions/workflows/tests.yml/badge.svg)](https://github.com/georgeantonopoulos/Basecamp-MCP-Server/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Connect Claude, Cursor, Codex and other AI assistants to your **Basecamp 3 or 4** account. Ask in plain language to find, read, create and update projects, to-dos, messages, card tables, schedules, documents and more: 210 Basecamp operations in all.

> "What's overdue across all my projects?" · "Summarise this week's messages in the Website project." · "Move this card to Done and comment that it shipped."

## Contents

- [Quick start](#quick-start)
- [Add it to your AI app](#add-it-to-your-ai-app)
- [What it can do](#what-it-can-do)
- [All 210 tools](#all-210-tools)
- [Settings and sign-in](#settings-and-sign-in)
- [Troubleshooting](#troubleshooting)
- [Run from a git checkout](#run-from-a-git-checkout)
- [Security](#security)

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (it installs Python for you) and a Basecamp 3 or 4 account. Setup takes about five minutes.

**1. Install uv**, if you don't have it:

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**2. Sign in to Basecamp:**

```bash
uvx basecamp-mcp-server login
```

The first time, it walks you through registering a free Basecamp app at [launchpad.37signals.com/integrations](https://launchpad.37signals.com/integrations) (set its **Redirect URI** to `http://localhost:8000/auth/callback`), then asks for the Client ID and Client Secret it shows you. Your browser then opens for Basecamp sign-in, and the token is saved for you. Tokens refresh automatically after that.

**3. Add the server to your AI app**, using the snippet from the next section, and restart the app.

Check everything is working at any time:

```bash
uvx basecamp-mcp-server status
```

## Add it to your AI app

`uvx basecamp-mcp-server config <app>` prints the exact snippet for your machine. The app can be `claude-desktop`, `cursor`, `claude-code`, `codex` or `generic`.

<details open>
<summary><b>Claude Desktop</b></summary>

Open **Settings → Developer → Edit Config** and add:

```json
{
  "mcpServers": {
    "basecamp": {
      "command": "uvx",
      "args": ["basecamp-mcp-server"]
    }
  }
}
```

Quit Claude Desktop completely and reopen it. If it says it can't find `uvx`, use the full path that `uvx basecamp-mcp-server config claude-desktop` prints.

</details>

<details>
<summary><b>Claude Code</b></summary>

```bash
claude mcp add basecamp -- uvx basecamp-mcp-server
```

</details>

<details>
<summary><b>Cursor</b></summary>

Add the same JSON as Claude Desktop to `~/.cursor/mcp.json` (or `.cursor/mcp.json` in a project), then restart Cursor and check **Settings → MCP**.

</details>

<details>
<summary><b>Codex</b></summary>

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.basecamp]
command = "uvx"
args = ["basecamp-mcp-server"]
```

</details>

<details>
<summary><b>Any other MCP client</b></summary>

Run `uvx basecamp-mcp-server` as a local (stdio) MCP server. The JSON above works for most clients.

</details>

### Four tools or all 210?

By default the server shows your AI app **four small tools** that find and run the right Basecamp operation on demand. That keeps the app's context small, and it can still reach all 210 operations. Reading and changing data are separate tools, so apps that ask before making changes still do.

To list all 210 tools up front instead, add `--full`: `"args": ["basecamp-mcp-server", "--full"]`.

### Run it as a web address (HTTP)

Apps that connect to a URL instead of starting a program can use HTTP mode:

```bash
uvx basecamp-mcp-server serve            # http://127.0.0.1:8765/mcp, this machine only
uvx basecamp-mcp-server serve --host 0.0.0.0 --port 9000   # reachable from other machines
```

Anyone who can reach the address acts in Basecamp as you, so every request must carry an access key: `Authorization: Bearer <key>`. The first `serve` creates the key, saves it to the settings `.env` as `BASECAMP_MCP_HTTP_TOKEN` and prints it with a ready-made Claude Code command:

```bash
claude mcp add --transport http basecamp http://127.0.0.1:8765/mcp --header "Authorization: Bearer <key>"
```

The server speaks plain HTTP. Before using it across a network you don't control, put it behind HTTPS (a reverse proxy or a tunnel), or the key travels unencrypted. Apps that only offer OAuth sign-in for remote servers (for example claude.ai custom connectors) can't send a fixed key yet. `--full` works here too: `serve --full`.

## What it can do

- **Projects and people:** list, create and update projects and templates; see who's on a project and grant or revoke access.
- **To-dos:** read, create, assign, complete, move and archive to-dos and to-do lists; see what's assigned to anyone and what's overdue.
- **Messages and comments:** read and post messages (or save drafts), pin them, manage categories, and comment on anything.
- **Chat and check-ins:** read and post in Campfire chats; create, pause and read automatic check-in questions and answers.
- **Schedules:** read, create and update events, including recurring ones.
- **Card tables:** work with columns, cards and card steps; move cards between columns.
- **Files and documents:** list, read and create documents; download uploads and inline attachments straight into the conversation.
- **Search and activity:** search the whole account; browse activity timelines and account-wide feeds of messages, files, to-dos and cards.
- **Time and progress:** timesheets, progress gauges and Hill Charts.
- **Personal and admin:** notifications, bookmarks, your private note, subscriptions, webhooks and project tools.

Big lists (projects, to-dos, comments, messages, cards, assignments) come back as compact summaries so they fit in the AI's context. Those tools take `detail: "full"` when you need every field, or set `BASECAMP_MCP_FULL_RESPONSES=1` to make that the default.

## All 210 tools

Grouped the same way the server groups them for discovery. Click a group to expand it.

<details>
<summary><b>Projects and people</b> (18 tools)</summary>

- `create_project` — Create a Basecamp project
- `create_project_from_template` — Start constructing a project from a Basecamp template
- `create_template` — Create a Basecamp project template
- `get_assignable_people` — Get all people who can have to-dos assigned to them
- `get_people` — Get people available in the authenticated Basecamp account
- `get_person` — Get one Basecamp person's profile
- `get_pingable_people` — Get Basecamp people who can be pinged
- `get_project` — Get one project's details, including its dock IDs
- `get_project_construction` — Get the status of a project being constructed from a template
- `get_project_people` — Get active people on a Basecamp project
- `get_projects` — List Basecamp projects. Returns a compact summary by default
- `get_template` — Get a Basecamp project template
- `get_templates` — List visible Basecamp project templates
- `trash_project` — Move a Basecamp project to the trash
- `trash_template` — Move a Basecamp project template to the trash
- `update_project` — Update a project's name, description, access policy, or date range
- `update_project_people` — Grant, revoke, or invite people on a Basecamp project
- `update_template` — Update a Basecamp project template

</details>

<details>
<summary><b>Todos and assignments</b> (25 tools)</summary>

- `archive_todo` — Archive a todo item
- `complete_todo` — Mark a todo item as complete
- `create_todo` — Create a new todo item in a todo list
- `create_todolist` — Create a new todo list in a project
- `create_todolist_group` — Create a new group inside a todo list
- `delete_todo` — Move a todo item to the trash
- `deprioritize_assignment` — Remove an assignment from the authenticated user's Up Next list
- `get_completed_assignments` — Get the authenticated user's completed assignments
- `get_due_assignments` — Get the authenticated user's assignments by due-date scope
- `get_my_assignments` — Get the authenticated user's active assignments grouped by priority
- `get_overdue_todos` — Get overdue to-dos for the WHOLE ACCOUNT, grouped by how late they are
- `get_person_assignments` — Get all active, pending to-dos assigned to a specific person
- `get_todo` — Get a single todo item by its ID
- `get_todolist` — Get a specific todo list by ID
- `get_todolist_groups` — Get all groups in a todo list
- `get_todolists` — Get todo lists for a project
- `get_todos` — Get todos from a todo list
- `prioritize_assignment` — Add an assignment to the authenticated user's Up Next list
- `reorder_priority` — Move an assignment to a position in the authenticated user's Up Next list
- `reposition_todo` — Reposition a todo within its list, or move it to another list or group
- `reposition_todolist_group` — Reposition a todo list group to a new location within its list
- `trash_todolist` — Move a todo list to the trash
- `uncomplete_todo` — Mark a todo item as incomplete
- `update_todo` — Update an existing todo item
- `update_todolist` — Update an existing todo list

</details>

<details>
<summary><b>Messages and comments</b> (24 tools)</summary>

- `create_comment` — Create a comment on a Basecamp item
- `create_draft_message` — Create a draft message on a project's message board without publishing it
- `create_message` — Create a new message on a project's message board
- `create_message_category` — Create a message type/category
- `delete_comment` — Delete a comment by moving it to the project's trash (Basecamp has no hard delete)
- `delete_message_category` — Delete a message type/category
- `get_comment` — Get a specific comment by ID
- `get_comments` — Get comments for a Basecamp item
- `get_forward` — Get a specific forwarded email by ID
- `get_forwards` — Get all forwarded emails from a project's inbox
- `get_inbox` — Get the inbox for a project (for email forwards)
- `get_inbox_replies` — Get all replies to a forwarded email
- `get_inbox_reply` — Get a specific reply to a forwarded email
- `get_message` — Get a specific message by ID
- `get_message_board` — Get the message board for a project
- `get_message_categories` — Get message categories (types) for a project
- `get_message_category` — Get one message type/category
- `get_messages` — Get all messages from a project's message board
- `pin_message` — Pin a message to the top of its message board
- `trash_forward` — Move a forwarded email to trash
- `unpin_message` — Remove a message from the top of its message board
- `update_comment` — Update a comment's content
- `update_message` — Update one or more fields on a message
- `update_message_category` — Update a message type/category

</details>

<details>
<summary><b>Campfires and check-ins</b> (17 tools)</summary>

- `create_campfire_line` — Create a plain-text line in a Basecamp campfire
- `create_question` — Create a question in a Basecamp automatic check-ins questionnaire
- `delete_campfire_line` — Permanently delete a line from a Basecamp campfire
- `get_campfire_line` — Get one line from a Basecamp campfire
- `get_campfire_lines` — Get recent messages from a Basecamp campfire (chat room)
- `get_campfires` — List campfire/chat rooms enabled in a project
- `get_daily_check_ins` — Get project's daily checking questionnaire
- `get_question` — Get one automatic check-in question
- `get_question_answer` — Get one automatic check-in answer
- `get_question_answerers` — List people who have answered a Basecamp automatic check-in question
- `get_question_answers` — Get answers on daily check-in question
- `get_question_reminders` — Get pending automatic check-in reminders for the authenticated user
- `get_questionnaire` — Get the automatic check-ins questionnaire for a project
- `get_questions` — Get questions from an automatic check-ins questionnaire
- `pause_question` — Pause a Basecamp automatic check-in question
- `resume_question` — Resume a paused Basecamp automatic check-in question
- `update_question` — Update selected fields on a Basecamp automatic check-in question

</details>

<details>
<summary><b>Schedules and calendars</b> (13 tools)</summary>

- `create_lineup_marker` — Create an account-wide Basecamp Lineup marker
- `create_schedule_entry` — Create a schedule entry in a Basecamp project's schedule
- `delete_lineup_marker` — Delete an account-wide Basecamp Lineup marker
- `get_calendar` — Get a Basecamp calendar by ID
- `get_lineup_markers` — List account-wide Basecamp Lineup markers
- `get_schedule` — Get the schedule for a Basecamp project
- `get_schedule_entries` — Get schedule entries for a Basecamp project
- `get_schedule_entry` — Get one schedule entry from a Basecamp project
- `get_schedule_entry_occurrence` — Get one occurrence of a recurring schedule entry
- `get_upcoming_schedule` — Get upcoming events and due work across all accessible projects
- `update_calendar` — Update a Basecamp calendar's display color
- `update_lineup_marker` — Update an account-wide Basecamp Lineup marker
- `update_schedule_entry` — Update one or more fields on a Basecamp schedule entry

</details>

<details>
<summary><b>Card tables</b> (29 tools)</summary>

- `complete_card` — Mark a card as complete
- `complete_card_step` — Mark a card step as complete
- `create_card` — Create a new card in a column
- `create_card_step` — Create a new step (sub-task) for a card
- `create_card_table_wormhole` — Create a cross-project card-table wormhole
- `create_column` — Create a new column in a card table
- `delete_card_step` — Delete a card step
- `delete_card_table_wormhole` — Delete a card-table wormhole
- `get_card` — Get details for a specific card
- `get_card_step` — Get details for a specific card step
- `get_card_steps` — Get all steps (sub-tasks) for a card
- `get_card_table` — Get the card table details for a project, including its columns
- `get_card_tables` — Get all card tables for a project
- `get_cards` — Get all cards in a column
- `get_column` — Get details for a specific column
- `get_columns` — Get all columns in a card table
- `move_card` — Move a card to a column or linked cross-project wormhole
- `move_column` — Move a column to a new position
- `put_column_on_hold` — Put a column on hold (freeze work)
- `remove_column_hold` — Remove hold from a column (unfreeze work)
- `uncomplete_card` — Mark a card as incomplete
- `uncomplete_card_step` — Mark a card step as incomplete
- `unwatch_column` — Unsubscribe from notifications for a column
- `update_card` — Update a card
- `update_card_step` — Update a card step
- `update_card_table_wormhole` — Change a card-table wormhole's destination column
- `update_column` — Update a column title
- `update_column_color` — Update a column color
- `watch_column` — Subscribe to notifications for changes in a column

</details>

<details>
<summary><b>Files and documents</b> (20 tools)</summary>

- `archive_recording` — Archive any Basecamp recording
- `create_attachment` — Upload a file as an attachment
- `create_document` — Create a document in a vault
- `create_draft_document` — Create a draft document in a vault without publishing it
- `create_upload_version` — Replace an upload's file while preserving its recording URL
- `download_attachment` — Download an inline comment/message attachment as MCP content
- `download_upload` — Download the binary content of an upload (PDF, image, document, ...)
- `get_document` — Get a single document
- `get_documents` — List documents in a vault
- `get_recordings` — List every recording of one supported type in a project or account
- `get_upload` — Get details for a specific upload
- `get_upload_versions` — Get raw version events for an upload, optionally filtered by action
- `get_uploads` — List uploads in a project or vault
- `get_vaults` — List child vaults in a vault
- `restore_recording` — Restore an archived Basecamp recording to active status
- `trash_document` — Move a document to trash
- `trash_recording` — Move any Basecamp recording to the trash
- `update_document` — Update a document
- `update_recording_visibility` — Toggle client visibility for a Basecamp recording
- `update_upload` — Update an upload's metadata without replacing its file

</details>

<details>
<summary><b>Search, activity, and reports</b> (15 tools)</summary>

- `get_events` — Get events for a recording
- `get_everything_cards` — Get filtered cards grouped by project across the whole account
- `get_everything_checkins` — Get automatic check-in answers across every accessible project
- `get_everything_comments` — Get recent comments across every accessible Basecamp project
- `get_everything_files` — Get files across every accessible project, optionally filtered by kind or creator
- `get_everything_forwards` — Get inbox forwards across every accessible Basecamp project
- `get_everything_messages` — Get recent messages across every accessible Basecamp project
- `get_everything_todos` — Get filtered to-dos grouped by project across the whole account
- `get_person_timeline` — Get timeline activity created by one Basecamp person
- `get_project_timeline` — Get recent activity within one Basecamp project
- `get_search_metadata` — Get the valid filters and content types for native Basecamp search
- `get_timeline` — Get recent activity across every accessible Basecamp project
- `global_search` — Search projects, todos and campfire messages across all projects
- `search_basecamp` — Search across Basecamp projects, todos, and messages
- `search_recordings` — Search Basecamp content, returning one page or at most ``limit`` results

</details>

<details>
<summary><b>Timesheets and progress</b> (17 tools)</summary>

- `create_gauge_needle` — Record a new progress update for a Basecamp project gauge
- `create_timesheet_entry` — Log time against a Basecamp timesheetable recording
- `delete_gauge_needle` — Permanently delete a Basecamp gauge needle
- `delete_timesheet_entry` — Permanently delete a Basecamp timesheet entry
- `get_gauge_needle` — Get one Basecamp gauge needle
- `get_gauge_needles` — Get a project's gauge history, newest first
- `get_gauges` — List project gauges across the authenticated Basecamp account
- `get_hill_chart` — Get the Basecamp Hill Chart for a to-do set
- `get_project_hill_chart` — Resolve and get a project's Basecamp Hill Chart
- `get_project_timesheet` — Get paginated timesheet entries for a Basecamp project
- `get_recording_timesheet` — Get paginated timesheet entries for a Basecamp recording
- `get_timesheet_entry` — Get one Basecamp timesheet entry
- `get_timesheet_report` — Get the account-wide, non-paginated Basecamp timesheet report
- `toggle_gauge` — Enable or disable a Basecamp project's gauge
- `update_gauge_needle` — Update the description of a Basecamp gauge needle
- `update_hill_chart_settings` — Track or untrack to-do lists on a Basecamp Hill Chart
- `update_timesheet_entry` — Update selected fields on a Basecamp timesheet entry

</details>

<details>
<summary><b>Notifications and personal tools</b> (16 tools)</summary>

- `create_bookmark` — Bookmark a Basecamp recording for the authenticated user
- `delete_bookmark` — Remove a recording from the authenticated user's bookmarks
- `get_bookmark_status` — Get the authenticated user's bookmark status for a recording
- `get_bubble_ups` — Get the authenticated user's current and scheduled bubble-ups
- `get_my_bookmarks` — Get recordings bookmarked by the authenticated user
- `get_my_drafts` — Get unpublished drafts owned by the authenticated user
- `get_my_note` — Get the authenticated user's personal Basecamp note
- `get_my_profile` — Get the authenticated person's Basecamp profile
- `get_notifications` — Get the authenticated user's grouped Basecamp notification inbox
- `get_subscription` — Get subscription state and subscribers for a Basecamp recording
- `mark_notifications_read` — Mark notification readable SGIDs as read
- `subscribe_to_recording` — Subscribe the authenticated user to a Basecamp recording
- `unsubscribe_from_recording` — Unsubscribe the authenticated user from a Basecamp recording
- `update_my_note` — Replace the authenticated user's personal Basecamp note
- `update_question_notification_settings` — Update the authenticated user's automatic check-in notification settings
- `update_subscription` — Add or remove people from a recording's subscriber list

</details>

<details>
<summary><b>Administration and integrations</b> (16 tools)</summary>

- `create_dock_tool` — Add a tool to a Basecamp project's dock
- `create_webhook` — Create a webhook
- `delete_webhook` — Delete a webhook
- `disable_dock_tool` — Hide a recording from a Basecamp project's dock without deleting it
- `enable_dock_tool` — Enable a recording in a Basecamp project's dock
- `get_account` — Get the Basecamp account associated with the current access token
- `get_dock_tool` — Get one Basecamp project dock tool
- `get_webhook` — Get one project webhook and its recent deliveries
- `get_webhooks` — List webhooks for a project
- `remove_account_logo` — Remove the account logo (administrator/owner only)
- `reposition_dock_tool` — Move a Basecamp project dock tool to a one-based position
- `trash_dock_tool` — Permanently delete a Basecamp dock tool and its content
- `update_account_logo` — Upload or replace the account logo (administrator/owner only)
- `update_account_name` — Rename the current Basecamp account (owner only)
- `update_dock_tool` — Rename a Basecamp project dock tool
- `update_webhook` — Update a project webhook destination, event types, or active state

</details>


> **Reading files in chat.** `download_upload` and `download_attachment` return files as MCP content. Claude Code passes PDFs, images and other files to the model. Claude Desktop and claude.ai currently pass images only; other file types are rejected by the app, not by this server.

## Settings and sign-in

The installed server keeps its settings in one folder:

| System | Folder |
| --- | --- |
| macOS and Linux | `~/.config/basecamp-mcp-server/` (or `$XDG_CONFIG_HOME/basecamp-mcp-server/`) |
| Windows | `%APPDATA%\basecamp-mcp-server\` |

It holds `.env` (your Basecamp app's Client ID and Secret), `oauth_tokens.json` (your sign-in) and log files. The `.env` and token files are readable only by you. To use a different folder, set `BASECAMP_MCP_HOME`.

**Several Basecamp accounts?** `login` asks which one to use, or you can pass `--account-id 1234567`. The ID is the number in your Basecamp URL: `https://3.basecamp.com/1234567/projects`.

**Signing in on a machine without a browser?** Run `uvx basecamp-mcp-server login --no-browser`, open the printed link on any browser that can reach `localhost` on that machine, and approve.

**Other settings** go in the environment or as lines in the settings `.env` file. `BASECAMP_MCP_HOME` is the exception: it says where that file is, so set it in the environment, or in your AI app's `env` block (`config` adds it for you).

| Variable | What it does |
| --- | --- |
| `BASECAMP_MCP_HOME` | Settings folder (see above). Environment only. |
| `BASECAMP_MCP_TOKEN_FILE` | Token file location, for example on a mounted volume. |
| `BASECAMP_REDIRECT_URI` | Must match your Basecamp app. Default `http://localhost:8000/auth/callback`. |
| `BASECAMP_ACCOUNT_ID` | Fallback account if the token doesn't record one. |
| `USER_AGENT` | Name sent to Basecamp's API. Basecamp asks for contact details; the default points to this project. |
| `BASECAMP_MCP_HTTP_TOKEN` | Access key for `serve`, at least 32 characters. Created for you if missing. |
| `BASECAMP_MCP_HTTP_HOST` / `BASECAMP_MCP_HTTP_PORT` | Default address for `serve` (`127.0.0.1`, `8765`). |
| `BASECAMP_MCP_FULL_RESPONSES` | `1` returns full records instead of compact summaries. |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| The Basecamp tools don't appear in your app | Quit the app completely and reopen it. Check the JSON is valid. |
| "spawn uvx ENOENT" or "command not found: uvx" | Desktop apps may not see your shell's PATH. Use the full path from `uvx basecamp-mcp-server config claude-desktop`. |
| "Authentication required" or "token expired" | Run `uvx basecamp-mcp-server login` again. |
| Login says the address is already in use | Something else is using port 8000 (often an old `oauth_app.py`). Stop it and retry. |
| Login says there's no Basecamp 3 or 4 account | You signed in as a user who isn't in a Basecamp 3/4 account. Sign in with a different user. |
| Basecamp shows "redirect_uri mismatch" | Your Basecamp app's Redirect URI must be exactly `http://localhost:8000/auth/callback` (or whatever `BASECAMP_REDIRECT_URI` is set to). |
| 403 errors on some tools | Some Basecamp features (Lineup, account settings, timesheets) need an account admin or owner, or need the feature turned on. |

Still stuck? `uvx basecamp-mcp-server status` shows where settings live and checks your sign-in. Logs are in the settings folder. Claude Desktop's own logs are in `~/Library/Logs/Claude/` (macOS) or `%APPDATA%\Claude\logs\` (Windows). Please [open an issue](https://github.com/georgeantonopoulos/Basecamp-MCP-Server/issues) with what you ran and the error.

## Run from a git checkout

Use this for development, or if you'd rather not install from PyPI. A checkout keeps its settings in the repository folder, as before.

```bash
git clone https://github.com/georgeantonopoulos/Basecamp-MCP-Server.git
cd Basecamp-MCP-Server
uv venv --python 3.12 venv
source venv/bin/activate     # Windows: venv\Scripts\activate
uv pip install -r requirements.txt
cp .env.example .env        # then fill in your Basecamp app details
python oauth_app.py         # sign in at http://localhost:8000
```

Then point your app at the checkout. These scripts write the config for you:

```bash
python generate_claude_desktop_config.py   # or generate_cursor_config.py, generate_codex_config.py
```

Each accepts `--full` for all 210 tools, or `--legacy` for the older JSON-RPC server.

Run the tests with `python -m pytest tests/`.

<details>
<summary><b>How the code is organised</b></summary>

| File | Role |
| --- | --- |
| [`basecamp_mcp_server/cli.py`](basecamp_mcp_server/cli.py) | The installed command: `login`, `status`, `config` and running the server. |
| [`basecamp_retrieval_mcp.py`](basecamp_retrieval_mcp.py) | Default server: four tools that discover and run the others. |
| [`basecamp_tool_retrieval.py`](basecamp_tool_retrieval.py) | Categories, read/write split, and ranking for discovery. |
| [`basecamp_fastmcp.py`](basecamp_fastmcp.py) | All 210 tool definitions; also the `--full` server. |
| [`basecamp_client.py`](basecamp_client.py) | Basecamp API client. |
| [`payload_shaping.py`](payload_shaping.py) | Compact summaries for large responses. |
| [`basecamp_oauth.py`](basecamp_oauth.py), [`auth_manager.py`](auth_manager.py), [`token_storage.py`](token_storage.py) | Sign-in, automatic token refresh, and token storage. |
| [`oauth_app.py`](oauth_app.py) | Browser sign-in page for git checkouts. |
| [`mcp_server_cli.py`](mcp_server_cli.py) | Older JSON-RPC server, kept for compatibility. |

</details>

## Security

- Your Basecamp app's secret and your token stay on your machine, in files only you can read. Never commit `.env` or `oauth_tokens.json`.
- Sign-in uses a one-time random check value, and the local sign-in page only accepts the response it's waiting for.
- Write tools are marked as such, so MCP apps that ask before making changes will ask.
- This server is built to run locally for one person. Read [the design notes](https://github.com/georgeantonopoulos/Basecamp-MCP-Server/blob/codex/central-hosting-design/CENTRAL_HOSTING_DESIGN.md) before hosting it for a team.

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
