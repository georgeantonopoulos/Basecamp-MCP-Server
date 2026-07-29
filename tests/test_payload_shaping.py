#!/usr/bin/env python3
"""Tests for MCP-boundary payload shaping.

Basecamp's list endpoints return far more than an LLM caller can use — a
24-project account returns ~149k characters from projects.json, of which the
fields identifying a project are under 1%. That overflows the MCP tool-result
limit, so results spill to disk and have to be parsed out of band.

basecamp_fastmcp trims payloads on the way out: `_NOISE_KEYS` are dropped
unconditionally, and `detail="summary"` (the default) projects records down to
identity/scheduling fields. The client layer is untouched and still returns
full API fidelity.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import basecamp_fastmcp as bf


def run(coro):
    return asyncio.run(coro)


async def _fake_run_sync(func, *args, **kwargs):
    """Stand-in for _run_sync: call through without a thread pool."""
    return func(*args, **kwargs)


PROJECT = {
    "id": 1, "name": "Acme Rebuild", "status": "active", "purpose": "topic",
    "description": "Website rebuild", "app_url": "https://app.basecamp.com/1/projects/1",
    "url": "https://3.basecampapi.com/1/projects/1.json",
    "bookmark_url": "https://3.basecampapi.com/1/my/bookmarks/AAA.json",
    "star_url": "https://3.basecampapi.com/1/projects/1/star.json",
    "created_at": "2026-01-01T00:00:00Z",
    "people": {"team": {"count": 1, "sample": [
        {"id": 9, "name": "Joe West", "avatar_url": "https://cdn/avatar",
         "attachable_sgid": "BAh7CEkiCG..."}]}},
    "dock": [
        {"id": 11, "name": "todoset", "title": "To-dos", "enabled": True,
         "url": "https://3.basecampapi.com/1/buckets/1/todosets/11.json",
         "app_url": "https://app.basecamp.com/1/buckets/1/todosets/11"},
        {"id": 12, "name": "chat", "title": "Chat", "enabled": False,
         "url": "https://3.basecampapi.com/1/buckets/1/chats/12.json",
         "app_url": "https://app.basecamp.com/1/buckets/1/chats/12"},
    ],
}

TODO = {
    "id": 5, "title": "Ship it", "content": "Ship it", "type": "Todo",
    "completed": False, "due_on": "2026-02-01", "has_description": True,
    "description": "<div>" + ("x" * 500) + "</div>",
    "app_url": "https://app.basecamp.com/1/buckets/1/todos/5",
    "bookmark_url": "https://3.basecampapi.com/1/my/bookmarks/BBB.json",
    "bucket": {"id": 1, "name": "Acme Rebuild", "type": "Project",
               "url": "https://3.basecampapi.com/1/projects/1.json"},
    "assignees": [{"id": 9, "name": "Joe West", "avatar_url": "https://cdn/a",
                   "attachable_sgid": "BAh7CEki", "email_address": "joe@x.com"}],
    "creator": {"id": 8, "name": "Ann", "avatar_url": "https://cdn/b",
                "attachable_sgid": "BAh7CEkj"},
}


class TestPrune(unittest.TestCase):
    """_NOISE_KEYS are removed at any nesting depth."""

    def test_drops_noise_keys_recursively(self):
        out = bf._prune(PROJECT)
        self.assertNotIn("bookmark_url", out)
        self.assertNotIn("star_url", out)
        sample = out["people"]["team"]["sample"][0]
        self.assertNotIn("avatar_url", sample)
        self.assertNotIn("attachable_sgid", sample)
        self.assertEqual(sample["name"], "Joe West")

    def test_keeps_everything_else(self):
        out = bf._prune(PROJECT)
        self.assertEqual(out["id"], 1)
        self.assertEqual(out["created_at"], "2026-01-01T00:00:00Z")
        self.assertIn("dock", out)

    def test_handles_scalars_and_lists(self):
        self.assertEqual(bf._prune("x"), "x")
        self.assertEqual(bf._prune([1, 2]), [1, 2])
        self.assertIsNone(bf._prune(None))


class TestProjectShaping(unittest.TestCase):

    def _projects(self, **kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_projects.return_value = [dict(PROJECT)]
            with patch.object(bf, "_run_sync", _fake_run_sync):
                return run(bf.get_projects(**kwargs))

    def test_summary_is_the_default_and_omits_bulk(self):
        r = self._projects()
        self.assertEqual(r["detail"], "summary")
        p = r["projects"][0]
        self.assertEqual(set(p), {"id", "name", "status", "purpose",
                                  "description", "app_url"})
        self.assertNotIn("people", p)
        self.assertNotIn("dock", p)

    def test_full_keeps_shape_minus_noise(self):
        r = self._projects(detail="full")
        p = r["projects"][0]
        self.assertIn("people", p)
        self.assertIn("dock", p)
        self.assertNotIn("bookmark_url", p)
        self.assertNotIn("star_url", p)

    def test_query_filters_by_name_case_insensitively(self):
        self.assertEqual(len(self._projects(query="acme")["projects"]), 1)
        self.assertEqual(len(self._projects(query="ACME")["projects"]), 1)
        self.assertEqual(len(self._projects(query="nope")["projects"]), 0)

    def test_status_filter(self):
        self.assertEqual(len(self._projects(status="active")["projects"]), 1)
        self.assertEqual(len(self._projects(status="archived")["projects"]), 0)

    def test_limit_reports_truncation(self):
        r = self._projects(limit=0)
        self.assertEqual(r["count"], 0)
        self.assertTrue(r["truncated"])
        self.assertEqual(r["matched"], 1)


MESSAGE = {
    "id": 7, "title": "Kickoff", "subject": "Kickoff", "type": "Message",
    "status": "active", "content": "<div>Welcome aboard</div>",
    "created_at": "2026-01-01T00:00:00Z", "comments_count": 2,
    "app_url": "https://app.basecamp.com/1/buckets/1/messages/7",
    "bookmark_url": "https://3.basecampapi.com/1/my/bookmarks/CCC.json",
    "creator": {"id": 8, "name": "Ann", "email_address": "ann@x.com",
                "avatar_url": "https://cdn/b", "attachable_sgid": "BAh",
                "time_zone": "Etc/UTC", "company": {"id": 3, "name": "Acme"},
                "can_manage_projects": True, "admin": False},
    "bucket": {"id": 1, "name": "Acme Rebuild", "type": "Project"},
}

COMMENT = {
    "id": 21, "type": "Comment", "status": "active",
    "content": "<div>Looks good to me</div>",
    "created_at": "2026-01-02T00:00:00Z",
    "app_url": "https://app.basecamp.com/1/buckets/1/comments/21",
    "content_attachments": [{"sgid": "BAh", "download_url": "https://x/y",
                             "filename": "a.png", "byte_size": 100}],
    "creator": dict(MESSAGE["creator"]),
    "parent": {"id": 7, "title": "Kickoff", "type": "Message"},
}


class TestCreatorReduction(unittest.TestCase):
    """`creator` is kept but reduced to id+name in every summary view."""

    def test_message_summary_keeps_content_and_trims_creator(self):
        out = bf._message_summary(bf._prune(dict(MESSAGE)))
        self.assertEqual(out["content"], "<div>Welcome aboard</div>")
        self.assertEqual(out["creator"], {"id": 8, "name": "Ann"})
        self.assertNotIn("bookmark_url", out)

    def test_comment_summary_keeps_content_drops_attachments(self):
        out = bf._comment_summary(bf._prune(dict(COMMENT)))
        self.assertEqual(out["content"], "<div>Looks good to me</div>")
        self.assertEqual(out["creator"], {"id": 8, "name": "Ann"})
        self.assertNotIn("content_attachments", out)
        self.assertEqual(out["parent"], {"id": 7, "title": "Kickoff",
                                        "type": "Message"})

    def test_full_detail_keeps_attachments_but_still_prunes_noise(self):
        out = bf._shape_records([dict(COMMENT)], "full", bf._comment_summary)[0]
        self.assertIn("content_attachments", out)
        self.assertNotIn("sgid", out["content_attachments"][0])
        self.assertNotIn("avatar_url", out["creator"])

    def test_creator_reduction_is_a_real_saving(self):
        import json
        full = len(json.dumps(bf._prune(dict(MESSAGE))))
        summ = len(json.dumps(bf._message_summary(bf._prune(dict(MESSAGE)))))
        self.assertLess(summ, full)


class TestTodoShaping(unittest.TestCase):

    def test_summary_drops_description_but_keeps_the_flag(self):
        out = bf._shape_todos([dict(TODO)], "summary")[0]
        self.assertNotIn("description", out)
        self.assertTrue(out["has_description"])
        self.assertEqual(out["due_on"], "2026-02-01")

    def test_summary_reduces_people_to_id_and_name(self):
        out = bf._shape_todos([dict(TODO)], "summary")[0]
        self.assertEqual(out["assignees"], [{"id": 9, "name": "Joe West"}])
        # creator is kept but reduced: a full person record is ~900 chars,
        # repeated on every row of a listing.
        self.assertEqual(out["creator"], {"id": 8, "name": "Ann"})

    def test_summary_reduces_bucket_to_identity(self):
        out = bf._shape_todos([dict(TODO)], "summary")[0]
        self.assertEqual(out["bucket"], {"id": 1, "name": "Acme Rebuild",
                                         "type": "Project"})

    def test_full_keeps_description_but_drops_noise(self):
        out = bf._shape_todos([dict(TODO)], "full")[0]
        self.assertIn("description", out)
        self.assertNotIn("bookmark_url", out)
        self.assertNotIn("avatar_url", out["assignees"][0])

    def test_summary_is_substantially_smaller(self):
        import json
        full = len(json.dumps(bf._shape_todos([dict(TODO)], "full")))
        summ = len(json.dumps(bf._shape_todos([dict(TODO)], "summary")))
        self.assertLess(summ, full / 2)


if __name__ == "__main__":
    unittest.main()
