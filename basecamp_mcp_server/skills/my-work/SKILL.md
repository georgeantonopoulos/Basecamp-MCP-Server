---
name: my-work
description: Triage the signed-in person's Basecamp work - overdue todos, what is due soon, and assigned cards - into a short prioritised list. Use when someone asks "what should I work on", "what's overdue", or wants a morning or end-of-day check of their Basecamp assignments.
---

# My work

Give the person one prioritised list of what is theirs. Read only unless they ask you to change something; then follow the `safe-changes` skill.

## How to call Basecamp

On the default (retrieval) server: `discover_basecamp_tools` (e.g. intent "my assignments") to get the exact name and arguments, then `call_basecamp_read_tool` with `{"name": "<operation>", "arguments": {...}}`. On the full server, call the operations directly.

## Steps

1. **Who am I.** `get_my_profile` for the person's id and name.
2. **Assigned work.** `get_my_assignments` returns todos and cards assigned to them, with priorities.
3. **Overdue.** `get_overdue_todos` with `assignee_id` set to their id.
4. **Due soon.** `get_due_assignments` with `scope` "due_today", "due_tomorrow" and "due_later_this_week" (other values: "overdue", "due_next_week", "due_later").
5. **Calendar.** `get_upcoming_schedule` with `window_starts_on` set to today and `window_ends_on` 7 days later (both YYYY-MM-DD), to spot clashes with deadlines.

## Write-up

1. **Overdue** first, oldest first, with project name and days over.
2. **Due today and tomorrow.**
3. **This week.**
4. **No date** - assigned items with no due date, at most five; say how many more.

One line per item: title, project, due date, link (`app_url`). End with at most one suggestion, such as "three overdue items are in the same list; want me to move their dates?" Do not change anything without a yes.
