"""Response shaping shared by both server paths.

Basecamp's API is generous: a 24-project account returns ~149k characters for
`projects.json`, of which the fields needed to identify a project are under 1%.
That overflows the MCP tool-result limit, so the host spills the result to a
file and the caller has to parse it out of band — which makes the most basic
discovery call unusable inline.

Shaping lives here, in one module imported by both `basecamp_fastmcp.py` and
`mcp_server_cli.py`, so the two server paths cannot return different shapes for
the same tool. `BasecampClient` is deliberately untouched and still returns the
original API payload.

Two controls, in precedence order:

1. An explicit per-call ``detail`` argument always wins.
2. Otherwise ``BASECAMP_MCP_FULL_RESPONSES=1`` makes ``full`` the default for
   list tools, restoring pre-shaping behaviour deployment-wide.
3. Otherwise the default is ``summary``.
"""

import os

SUMMARY = "summary"
FULL = "full"

#: Environment variable restoring full list responses deployment-wide.
FULL_RESPONSES_ENV = "BASECAMP_MCP_FULL_RESPONSES"

# Dropped at every detail level. None of these are actionable from an MCP
# caller: avatar/CDN links cannot be viewed, the *_url endpoints cannot be
# invoked through this server, and the sgid blobs are opaque handles only needed
# when composing an @mention (fetch the person record directly for that).
NOISE_KEYS = frozenset({
    "avatar_url",
    "attachable_sgid",
    "sgid",
    "bookmark_url",
    "star_url",
    "subscription_url",
    "comments_url",
    "boosts_url",
    "completion_url",
    "status_url",
})

# Kept when detail="summary" — enough to identify and choose a project.
PROJECT_SUMMARY_KEYS = (
    "id", "name", "status", "purpose", "description", "app_url",
    "created_at", "updated_at",
)

# Kept when detail="summary" on to-do shaped payloads. `description` is
# deliberately excluded (21%+ of those payloads) in favour of Basecamp's own
# `has_description` flag — fetch the single record when the body is wanted.
TODO_SUMMARY_KEYS = (
    "id", "title", "content", "type", "status", "completed",
    "due_on", "starts_on", "has_description", "comments_count",
    "app_url", "is_priority",
)

# Messages and comments: `content` IS the payload the caller came for, so it is
# never dropped or truncated — unlike a to-do's `description`, there is no
# has_description flag to fall back on and no way to identify the record
# without it. What gets trimmed is the surrounding metadata.
MESSAGE_SUMMARY_KEYS = (
    "id", "title", "subject", "type", "status", "content",
    "created_at", "updated_at", "comments_count", "app_url",
)
COMMENT_SUMMARY_KEYS = (
    "id", "type", "status", "content", "created_at", "updated_at", "app_url",
)

# Cards carry the same person-object weight as to-dos (issue #36 measured
# get_cards at 47% person objects, get_card_table at 63%).
CARD_SUMMARY_KEYS = (
    "id", "title", "content", "type", "status", "completed",
    "due_on", "has_description", "comments_count", "app_url", "position",
)
COLUMN_SUMMARY_KEYS = (
    "id", "title", "type", "status", "cards_count", "position", "color",
    "on_hold", "app_url", "description",
)

# Nested records reduced to id+name in every summary view. A full person record
# is ~900 characters — email address, timestamps, company, timezone and a dozen
# capability flags — repeated on every row of a listing.
BRIEF_NESTED_KEYS = ("creator", "bucket", "parent")

# Cap for an unbounded detail="full" project listing. Full records run ~2,700
# chars each, so a whole account overflows the tool-result limit; the caller
# sees `truncated`/`matched` and can page or narrow.
FULL_DETAIL_DEFAULT_LIMIT = 5


def full_responses_default() -> bool:
    """True when BASECAMP_MCP_FULL_RESPONSES asks for full list responses."""
    raw = (os.environ.get(FULL_RESPONSES_ENV) or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def resolve_detail(detail=None) -> str:
    """Resolve the effective detail level.

    An explicit per-call ``detail`` always wins, so a caller can ask for a
    summary even on a deployment that has opted out globally, and vice versa.
    """
    if detail in (SUMMARY, FULL):
        return detail
    return FULL if full_responses_default() else SUMMARY


def prune(obj):
    """Recursively strip NOISE_KEYS from any API payload."""
    if isinstance(obj, dict):
        return {k: prune(v) for k, v in obj.items() if k not in NOISE_KEYS}
    if isinstance(obj, list):
        return [prune(v) for v in obj]
    return obj


def person_brief(person):
    """Reduce a person record to what identifies them."""
    if not isinstance(person, dict):
        return person
    return {k: person[k] for k in ("id", "name") if k in person}


def brief_nested(record, out):
    """Copy creator/bucket/parent across, reduced to identifying fields."""
    for key in BRIEF_NESTED_KEYS:
        src = record.get(key)
        if not isinstance(src, dict):
            continue
        if key == "creator":
            out[key] = person_brief(src)
        else:
            out[key] = {k: src[k] for k in ("id", "name", "title", "type")
                        if k in src}
    return out


def project_tools(project):
    """Names of the project's enabled dock entries, e.g. ["todoset", "vault"].

    A cheap stand-in for the dock in a listing: it answers "does this project
    have a card table?" without the ~1,000 characters an entry costs. The dock
    IDs themselves come from get_project.
    """
    dock = project.get("dock")
    if not isinstance(dock, list):
        return []
    return [d.get("name") for d in dock
            if isinstance(d, dict) and d.get("enabled") and d.get("name")]


def project_summary(project):
    """Identity view of a project: no `people`, no `dock`, just enabled tools."""
    if not isinstance(project, dict):
        return project
    out = {k: project[k] for k in PROJECT_SUMMARY_KEYS if k in project}
    tools = project_tools(project)
    if tools:
        out["tools"] = tools
    return out


def trim_dock(project):
    """Drop the redundant API `url` from each dock entry, keeping `app_url`.

    Every dock entry carries both `url` and `app_url` for the same resource,
    which is ~1,000 wasted characters per project. Shared by get_project and
    get_projects(detail="full") so the two cannot drift apart.
    """
    if not isinstance(project, dict):
        return project
    dock = project.get("dock")
    if isinstance(dock, list):
        project["dock"] = [
            {k: v for k, v in item.items() if k != "url"}
            if isinstance(item, dict) else item
            for item in dock
        ]
    return project


def trim_people_sample(project):
    """Reduce each `people` group's sample to id+name.

    Note the sample is not guaranteed to be the full membership, so it is only
    ever exposed as a sample — never as a complete member list.
    """
    if not isinstance(project, dict):
        return project
    people = project.get("people")
    if isinstance(people, dict):
        for group in people.values():
            if isinstance(group, dict) and isinstance(group.get("sample"), list):
                group["sample"] = [person_brief(p) for p in group["sample"]]
    return project


def project_full(project):
    """Complete project record, minus the redundancies (dock url, people bulk)."""
    return trim_people_sample(trim_dock(project))


def _by_keys(record, keys):
    if not isinstance(record, dict):
        return record
    out = {k: record[k] for k in keys if k in record}
    return brief_nested(record, out)


def todo_summary(todo):
    """Identity/scheduling view of a to-do, with people reduced to id+name."""
    if not isinstance(todo, dict):
        return todo
    out = _by_keys(todo, TODO_SUMMARY_KEYS)
    if isinstance(todo.get("assignees"), list):
        out["assignees"] = [person_brief(p) for p in todo["assignees"]]
    return out


def card_summary(card):
    """Identity/scheduling view of a card, with people reduced to id+name."""
    if not isinstance(card, dict):
        return card
    out = _by_keys(card, CARD_SUMMARY_KEYS)
    if isinstance(card.get("assignees"), list):
        out["assignees"] = [person_brief(p) for p in card["assignees"]]
    return out


def column_summary(column):
    """Identity view of a card-table column, without its embedded cards."""
    if not isinstance(column, dict):
        return column
    out = _by_keys(column, COLUMN_SUMMARY_KEYS)
    cards = column.get("cards")
    if isinstance(cards, list):
        out["cards_count"] = out.get("cards_count", len(cards))
    return out


def message_summary(message):
    """Message with its content intact but metadata trimmed."""
    return _by_keys(message, MESSAGE_SUMMARY_KEYS)


def comment_summary(comment):
    """Comment with its content intact but metadata trimmed."""
    return _by_keys(comment, COMMENT_SUMMARY_KEYS)


def shape_records(records, detail, summarise):
    """Apply a detail level to a list of records using `summarise` for summary."""
    if not isinstance(records, list):
        return prune(records)
    if detail == FULL:
        return [prune(r) for r in records]
    return [summarise(prune(r)) for r in records]


def shape_todos(todos, detail):
    """Apply the chosen detail level to a list of to-do records."""
    return shape_records(todos, detail, todo_summary)


def shape_cards(cards, detail):
    """Apply the chosen detail level to a list of card records."""
    return shape_records(cards, detail, card_summary)


def shape_card_table(table, detail):
    """Shape a card table, whose columns embed their cards.

    A single board runs ~11k tokens on a real account because the same
    subscriber objects repeat in every column, so summary drops the embedded
    cards and keeps a per-column count instead.
    """
    table = prune(table)
    if not isinstance(table, dict) or detail == FULL:
        return table
    for key in ("lists", "columns"):
        cols = table.get(key)
        if isinstance(cols, list):
            table[key] = [column_summary(c) for c in cols]
    return table
