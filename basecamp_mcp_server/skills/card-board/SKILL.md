---
name: card-board
description: Read and work a Basecamp card table (kanban board) - show the board by column, find stale cards, create cards and move them between columns. Use when someone mentions a card table, kanban, board, columns, or moving a card.
---

# Card board

## How to call Basecamp

On the default (retrieval) server: `discover_basecamp_tools` with category `card_tables` gives the exact names and arguments. Reads go through `call_basecamp_read_tool`, changes through `call_basecamp_write_tool`, each as `{"name": "<operation>", "arguments": {...}}`. On the full server, call the operations directly.

## Reading the board

1. Find the project with `get_projects` (`query` = the name given).
2. `get_card_table` with `project_id` gives the table and its columns.
3. `get_cards` with `project_id` and each `column_id`.
4. Show it column by column, in board order: card title, assignees, due date. Mark a card **stale** when it has not been updated in 14 days, and **late** when `due_on` has passed.

## Changing the board

Follow the `safe-changes` skill: say exactly what will change and wait for a yes.

- **New card:** `create_card` with `project_id`, `column_id`, `title`, and optional `content` (HTML), `due_on` (YYYY-MM-DD).
- **Move a card:** `move_card` with `project_id`, `card_id`, target `column_id`, and optional `position` (1 is the top).
- **Edit a card:** `update_card` (title, content, due date, assignees).
- **Finish a card:** `complete_card`.
- **Steps on a card:** discover with intent "card steps".

After a change, read the card back with `get_card` and report what it now says, rather than assuming the change worked.
