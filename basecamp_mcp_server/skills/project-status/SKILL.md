---
name: project-status
description: Write a short status update for one Basecamp project - what moved, what is late, what is coming up and who is blocked. Use when someone asks how a project is going, wants a weekly digest, or needs a status note for a client or team.
---

# Project status

Produce a status note someone can read in a minute. Read only; never change anything.

## How to call Basecamp

On the default (retrieval) server, call operations through its four tools:

1. `discover_basecamp_tools` with the intent, e.g. "project timeline", to get the exact name and arguments.
2. `call_basecamp_read_tool` with `{"name": "<operation>", "arguments": {...}}`.

On the full server the operations below are tools in their own right; call them directly.

## Steps

1. **Find the project.** `get_projects` with `query` set to the name the user gave. If several match, ask which one.
2. **Recent activity.** `get_project_timeline` with `project_id` (and `limit` around 50). Group what happened by person and by tool (todos, messages, cards, docs).
3. **Late and due work.** `get_todolists` then `get_todos` per list (open todos by default). Pull out items past `due_on` and items due in the next 7 days. If the project has a card table, `get_card_table` and `get_cards` per column give the same for cards.
4. **Coming up.** `get_schedule_entries` with `project_id`, keeping the next 14 days.
5. **Progress, if tracked.** `get_project_hill_chart`; skip quietly if the project has none.

## Write-up

Use these headings, each a few bullets, and leave a heading out when it has nothing:

- **Done since last week** - shipped or completed items, with who did them.
- **Late** - item, owner, how many days over.
- **Due next 7 days** - item, owner, date.
- **Coming up** - schedule entries.
- **Needs attention** - anything stuck: overdue with no owner, cards untouched for two weeks, unanswered questions in messages.

Link each item with its `app_url` when the data has one. Use dates as written in Basecamp, and say which period the note covers.
