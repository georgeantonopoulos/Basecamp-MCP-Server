# Changelog

All notable changes to this project are documented here. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- **Clearer message when your login has no Basecamp account.** Signing in with a 37signals or Google login that isn't a member of any Basecamp 3 or 4 account now names the login, lists any older products it does have (Basecamp 2, Campfire and so on, in plain words), and says what to do: sign out at launchpad.37signals.com and sign in with the email you use for Basecamp, or get invited. The same message appears in `login`, on the local sign-in page (which no longer saves a token with no account behind it), in `status`, and in tool errors seen by the AI app. `status` also notices when you've lost access to the saved account and lists the accounts you can still use.

## [1.0.0] - 2026-11-09

First release on PyPI.

### Added

- **One-command install.** `uvx basecamp-mcp-server` runs the server with no clone or virtual environment. `uvx basecamp-mcp-server login` registers your Basecamp app details, opens the browser for sign-in and saves the token itself; no local web page to start by hand. `status` checks the saved sign-in against Basecamp, and `config <app>` prints the setup snippet for Claude Desktop, Claude Code, Cursor or Codex. Installed settings live in one per-user folder (`BASECAMP_MCP_HOME` to override); git checkouts keep working as before.
- Sign-in now stops with a clear message when the Basecamp login has no Basecamp 3/4 account, instead of saving a token that fails later. With several accounts, `login` asks which to use (`--account-id` to choose up front).
- 210 Basecamp operations (up from 79), with a retrieval-first default server that shows four discovery tools and finds the rest on demand (#51).
- OAuth token, refresh and identity requests time out after 30 seconds instead of hanging sign-in (#54, thanks @ranas-mukminov).

- Reports API tools ([bc-api sections/reports.md](https://github.com/basecamp/bc-api/blob/master/sections/reports.md)): `get_assignable_people` (`GET /reports/todos/assigned.json`), `get_person_assignments` (`GET /reports/todos/assigned/{person_id}.json` with optional `group_by: bucket|date`) and `get_overdue_todos` (`GET /reports/todos/overdue.json`). `get_person_assignments` returns one person's active, pending to-dos across all projects in a single call — previously this required iterating every project and todolist, which was slow and easy to get wrong (missed projects read as "no assignments"). The embedded `todos` list follows `Link`-header pagination defensively and merges pages into one report. All three tools are also exposed by the legacy `mcp_server_cli.py` server for compatibility.
- `completed` and `status` parameters for `get_todos`. The Basecamp to-dos
  endpoint returns only the active (incomplete) to-dos by default; callers can
  now pass `completed: true` to fetch the completed to-dos, or
  `status: "archived"`/`"trashed"` to fetch by recording status. The params are
  threaded through the existing `get_all_pages()` pagination, so completed sets
  are returned in full rather than only the first page.
- `publish` option for `create_message` and `create_document`. The tools still
  publish immediately by default, and callers can pass `publish: false` to omit
  `status: "active"` and create a Basecamp draft instead.
- `create_draft_message` and `create_draft_document` MCP tools as explicit,
  discoverable draft-first wrappers for agents that may miss optional flags.
- `download_upload` MCP tool for retrieving the binary content of a vault `Upload` recording (PDF, image, document, …) directly through MCP. Returns the file as `ImageContent` for image MIME types and as an `EmbeddedResource` (`BlobResourceContents`) for everything else, so the MCP host can forward the blob to the model and the file is read natively (PDF tables, images, OCR) without an out-of-band fetch. Caps the payload via `max_bytes` (default 25 MB) so the MCP transport and model context are not stressed by huge files.
- `download_attachment` MCP tool for retrieving inline comment/message attachments. Pass the `content_attachments[].download_url` returned by `get_comments` / `get_messages` and receive the file as MCP `ImageContent` (image MIME types) or `EmbeddedResource` (everything else). Required because inline attachments are `Attachment` objects, not `Upload` recordings — the `/uploads/{id}` endpoint returns 404 for their IDs. The implementation walks the 302 redirect to the pre-signed storage host manually and strips the OAuth `Authorization` header on the cross-host hop to avoid leaking the Bearer token. Honours a `max_bytes` guard (default 25 MB) via the caller-supplied `byte_size`, `Content-Length`, and a streaming cutoff.

### Fixed

- `delete_comment` now trashes the comment through Basecamp's documented route; it called an endpoint that doesn't exist and always failed.
- `update_schedule_entry` keeps the entry's times, description and all-day setting when you change only some fields. Basecamp rejected partial updates, and once times were sent it cleared the rest.
- `create_question` documents its schedule format and takes `respondents`; without them Basecamp rejected the guessed format or asked nobody.
- Project dock lookups for to-do sets, message boards, inboxes, and schedules
  now share consistent handling for missing or malformed dock data.
- All list helpers now follow Basecamp's `Link` header pagination via a shared
  `get_all_pages()` helper. Previously only `get_todos`, `get_todolist_groups`,
  `get_messages`, `get_forwards`, and `get_inbox_replies` paginated; the other
  list endpoints (`get_projects`, `get_todolists`, `get_people`, `get_campfires`,
  `get_campfire_lines`, `get_message_categories`, `get_schedule_entries`,
  `get_cards`, `get_events`, `get_webhooks`, `get_documents`, `get_uploads`)
  silently returned only the first page (15 items) — accounts with more than
  15 projects saw a truncated project list. Same root cause as #12, applied
  across the board.
- `get_schedule_entries` now discovers the schedule ID from the project dock
  (like `get_todoset`). It previously compared a `requests.Response` object
  against `list` and therefore always returned an empty list.
- Todo and card completion helpers now treat Basecamp's successful `204 No Content`
  responses as completed instead of raising an error.
- Card-step completion now uses Basecamp's documented card-table step completions
  endpoint with `completion: "on"` / `"off"`.

### Notes

- `download_upload` and `download_attachment` rely on the MCP host (the client application) forwarding `ImageContent` / `EmbeddedResource` blocks to the model. As of June 2026, Claude Code (CLI) supports both fully, including `application/pdf`. Claude Desktop / claude.ai web rejects non-image `EmbeddedResource` blocks with `"Resources of type 'application/pdf' are not currently supported"` — the bytes arrive at the host but never reach the model. No server-side workaround possible.
- `BASECAMP_MCP_TOKEN_FILE` environment variable to configure the OAuth token file path. Useful for containerized deployments where the application directory is read-only or ephemeral and the token store must live on a mounted volume. When unset, a git checkout keeps the token at `<project>/oauth_tokens.json` (previous default) and the installed package keeps it in the per-user settings folder. See [README — Settings and sign-in](README.md#settings-and-sign-in).
