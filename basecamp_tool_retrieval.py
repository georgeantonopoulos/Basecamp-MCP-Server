"""Compact discovery helpers for the full Basecamp MCP tool registry.

The MCP protocol does not currently provide portable category or semantic
filtering for ``tools/list``.  This module keeps the full FastMCP registry as
the source of truth while presenting a small, deterministic retrieval layer
to clients that do not perform their own tool search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence


ToolAccess = Literal["read", "write"]


@dataclass(frozen=True)
class ToolCategory:
    """A compact model-facing category description."""

    name: str
    title: str
    description: str
    keywords: tuple[str, ...]


CATEGORIES: tuple[ToolCategory, ...] = (
    ToolCategory(
        "projects_people",
        "Projects and people",
        "Projects, templates, project construction, people, profiles, and access.",
        ("project", "projects", "people", "person", "template", "team", "profile"),
    ),
    ToolCategory(
        "todos_assignments",
        "Todos and assignments",
        "Todo sets, lists, groups, todos, assignments, priorities, and completion.",
        ("todo", "todos", "assignment", "assignments", "priority", "task", "tasks"),
    ),
    ToolCategory(
        "messages_comments",
        "Messages and comments",
        "Message boards, messages, categories, comments, inbox forwards, and replies.",
        ("message", "messages", "comment", "comments", "forward", "inbox", "reply"),
    ),
    ToolCategory(
        "campfires_checkins",
        "Campfires and check-ins",
        "Campfire chats, automatic check-in questionnaires, questions, and answers.",
        ("campfire", "chat", "checkin", "check-in", "question", "questionnaire", "answer"),
    ),
    ToolCategory(
        "schedules_calendar",
        "Schedules and calendars",
        "Project schedules, recurring entries, calendars, and Lineup markers.",
        ("schedule", "calendar", "lineup", "event", "date"),
    ),
    ToolCategory(
        "card_tables",
        "Card tables",
        "Card tables, columns, cards, steps, holds, watchers, and wormholes.",
        ("card", "cards", "column", "kanban", "step", "wormhole"),
    ),
    ToolCategory(
        "files_documents",
        "Files and documents",
        "Vaults, uploads, attachments, documents, recordings, versions, and downloads.",
        ("file", "files", "document", "upload", "attachment", "vault", "recording", "download"),
    ),
    ToolCategory(
        "search_reports",
        "Search, activity, and reports",
        "Native search, account-wide feeds, timelines, activity, and cross-project reports.",
        ("search", "report", "timeline", "activity", "everything", "account-wide", "feed"),
    ),
    ToolCategory(
        "timesheets_progress",
        "Timesheets and progress",
        "Time entries, timesheet reports, gauges, needles, and Hill Charts.",
        ("time", "timesheet", "progress", "gauge", "needle", "hill", "chart"),
    ),
    ToolCategory(
        "notifications_personal",
        "Notifications and personal tools",
        "Notifications, subscriptions, bookmarks, drafts, personal notes, and personal views.",
        ("notification", "subscription", "bookmark", "draft", "personal", "note", "bubble"),
    ),
    ToolCategory(
        "administration_integrations",
        "Administration and integrations",
        "Account administration, dock tools, webhooks, logos, and client visibility.",
        ("admin", "account", "dock", "webhook", "integration", "logo", "visibility"),
    ),
)

CATEGORY_BY_NAME = {category.name: category for category in CATEGORIES}


_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("search_reports", ("search", "timeline", "everything_", "get_events")),
    ("timesheets_progress", ("timesheet", "gauge", "needle", "hill_chart")),
    ("todos_assignments", ("todo", "assignment", "priority")),
    ("messages_comments", ("message", "comment", "forward", "inbox", "reply")),
    ("notifications_personal", ("notification", "subscription", "subscribe", "unsubscribe", "bookmark", "my_", "personal", "bubble")),
    ("campfires_checkins", ("campfire", "question", "questionnaire", "checkin", "check_in")),
    ("schedules_calendar", ("schedule", "calendar", "lineup")),
    ("card_tables", ("card", "column", "wormhole")),
    ("files_documents", ("upload", "document", "attachment", "vault", "recording", "download")),
    ("administration_integrations", ("account", "dock", "webhook", "logo", "visibility")),
    ("projects_people", ("project", "people", "person", "template", "profile", "assignable")),
)

_READ_PREFIXES = ("get_", "search_", "download_")
_READ_NAMES = {"global_search"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {"a", "an", "the", "to", "for", "in", "on", "of", "basecamp", "please", "tool"}


def tool_access(name: str) -> ToolAccess:
    """Classify a tool conservatively for the public read/write dispatchers."""
    if name.startswith(_READ_PREFIXES) or name in _READ_NAMES:
        return "read"
    return "write"


def tool_category(name: str) -> str:
    """Return one stable category for a registered Basecamp tool name."""
    lowered = name.lower()
    for category, patterns in _CATEGORY_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return category
    return "administration_integrations"


def compact_description(description: Optional[str], limit: int = 280) -> str:
    """Collapse a tool docstring into a short discovery description."""
    text = " ".join((description or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _tokens(value: str) -> set[str]:
    return {
        token for token in _TOKEN_RE.findall(value.lower())
        if token not in _STOP_WORDS
    }


def _normalized_terms(value: str) -> str:
    return " ".join(
        token for token in _TOKEN_RE.findall(value.lower())
        if token not in _STOP_WORDS
    )


def _tool_field(tool: Any, snake: str, camel: str) -> Any:
    if hasattr(tool, snake):
        return getattr(tool, snake)
    return getattr(tool, camel, None)


def tool_input_schema(tool: Any) -> Dict[str, Any]:
    schema = _tool_field(tool, "input_schema", "inputSchema")
    return schema if isinstance(schema, dict) else {"type": "object"}


def serialize_tool(tool: Any, *, include_schema: bool = True) -> Dict[str, Any]:
    """Serialize only the metadata needed to select and call one tool."""
    name = tool.name
    access = tool_access(name)
    result: Dict[str, Any] = {
        "name": name,
        "title": getattr(tool, "title", None) or name.replace("_", " ").title(),
        "description": compact_description(getattr(tool, "description", None)),
        "category": tool_category(name),
        "access": access,
        "executor": f"call_basecamp_{access}_tool",
    }
    if include_schema:
        result["input_schema"] = tool_input_schema(tool)
    return result


def _score_tool(tool: Any, query: str, category: Optional[str]) -> int:
    name = tool.name.lower()
    description = compact_description(getattr(tool, "description", None), 800).lower()
    assigned_category = tool_category(name)
    category_info = CATEGORY_BY_NAME[assigned_category]
    normalized_query = _normalized_terms(query)
    query_tokens = _tokens(query)
    name_tokens = _tokens(name)
    description_tokens = _tokens(description)
    category_tokens = _tokens(
        " ".join((category_info.name, category_info.title, category_info.description, *category_info.keywords))
    )

    score = 0
    normalized_name = _normalized_terms(name)
    if normalized_query and normalized_query == normalized_name:
        score += 250
    elif normalized_query and normalized_query in normalized_name:
        score += 100
    score += 30 * len(query_tokens & name_tokens)
    score += 5 * len(query_tokens & description_tokens)
    score += 4 * len(query_tokens & category_tokens)
    if category and assigned_category == category:
        score += 20
    return score


def retrieve_tools(
    tools: Sequence[Any],
    *,
    intent: str,
    category: Optional[str] = None,
    access: Literal["read", "write", "all"] = "all",
    limit: int = 6,
    include_schema: bool = True,
) -> List[Dict[str, Any]]:
    """Return a bounded, ranked subset of registered tools."""
    if category is not None and category not in CATEGORY_BY_NAME:
        raise ValueError(
            f"Unknown category '{category}'. Use list_basecamp_categories for valid names."
        )
    if access not in {"read", "write", "all"}:
        raise ValueError("access must be read, write, or all")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 12:
        raise ValueError("limit must be between 1 and 12")
    if not intent.strip() and category is None:
        raise ValueError("intent or category is required")

    candidates = []
    for tool in tools:
        if category and tool_category(tool.name) != category:
            continue
        if access != "all" and tool_access(tool.name) != access:
            continue
        score = _score_tool(tool, intent, category)
        candidates.append((score, tool.name, tool))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    if intent.strip():
        candidates = [item for item in candidates if item[0] > 0]
    return [
        serialize_tool(tool, include_schema=include_schema)
        for _, _, tool in candidates[:limit]
    ]


def category_summaries(tools: Iterable[Any]) -> List[Dict[str, Any]]:
    """Return category descriptions with read/write counts."""
    counts = {
        category.name: {"read": 0, "write": 0}
        for category in CATEGORIES
    }
    for tool in tools:
        counts[tool_category(tool.name)][tool_access(tool.name)] += 1

    return [
        {
            "name": category.name,
            "title": category.title,
            "description": category.description,
            "read_tools": counts[category.name]["read"],
            "write_tools": counts[category.name]["write"],
            "total_tools": sum(counts[category.name].values()),
        }
        for category in CATEGORIES
    ]
