"""Small response-shaping helpers for Basecamp recordings."""

from html import unescape
import re


_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def compact_recording(recording, query=None):
    """Keep routing, asset, and query-context fields from a recording."""
    summary = {
        key: recording[key]
        for key in (
            "id",
            "title",
            "type",
            "app_url",
            "filename",
            "content_type",
            "byte_size",
            "width",
            "height",
            "download_url",
            "app_download_url",
        )
        if recording.get(key) is not None
    }

    parent = recording.get("parent")
    if parent:
        summary["parent"] = {
            key: parent[key]
            for key in ("id", "title", "type", "app_url")
            if parent.get(key) is not None
        }

    attachments = recording.get("content_attachments") or []
    if attachments:
        summary["content_attachments"] = [
            {
                key: attachment[key]
                for key in (
                    "id",
                    "filename",
                    "content_type",
                    "byte_size",
                    "width",
                    "height",
                    "download_url",
                    "preview_url",
                )
                if attachment.get(key) is not None
            }
            for attachment in attachments
        ]

    content = recording.get("content") or recording.get("description") or ""
    if content:
        plain_text = _SPACE_RE.sub(" ", unescape(_TAG_RE.sub(" ", content))).strip()
        if query:
            match_at = plain_text.casefold().find(query.casefold())
            if match_at >= 0:
                start = max(0, match_at - 180)
                end = min(len(plain_text), match_at + len(query) + 220)
                summary["query_context"] = plain_text[start:end]

    return summary
