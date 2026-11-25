---
name: safe-changes
description: Rules for changing anything in Basecamp - confirm first, change one thing at a time, read it back, and never trash, delete or post to clients without a clear yes. Use before any Basecamp write - creating, updating, completing, moving, commenting, posting, trashing, archiving or changing who can see something.
---

# Safe changes in Basecamp

Basecamp is shared: a change notifies people, and some changes are hard to undo. Use these rules for every change.

## Before changing anything

1. **Read first.** Fetch the current item so you are changing what you think you are changing.
2. **Say exactly what will happen**, in one or two lines: the item (title and project), the change, and who will be notified. Example: "Move card 'Homepage copy' from Doing to Done in Website Refresh. The 3 people on the card get notified."
3. **Wait for a clear yes.** Silence, "sounds good in general" or an earlier yes to a different change does not count.

## Extra care

- **Trash, delete, archive, remove people, change access or client visibility:** always confirm, even when the person already asked for it, and name the item. Trashed items can be restored for a while (`restore_recording`); deleted items cannot.
- **Posting messages, comments or Campfire lines:** show the exact text before posting. Never post to a project that clients can see without saying so.
- **Bulk changes:** list every item first, then change them one at a time and stop at the first failure.
- **Never guess an id.** If the name matches more than one item, ask.

## How to call Basecamp

On the default (retrieval) server, changes go through `call_basecamp_write_tool` with `{"name": "<operation>", "arguments": {...}}`; use `discover_basecamp_tools` with `access` "write" to find the operation and its arguments. The server refuses a write sent through the read tool, and the other way round. On the full server, call the operations directly.

## After changing

Read the item back and report what it now says. If the call returned an error, say so plainly with the message; do not retry a write without asking.
