#!/usr/bin/env python3
"""The two server paths must return the same shapes for the same tool.

basecamp_fastmcp.py and mcp_server_cli.py are separate implementations over the
same client. If only one of them shapes its responses, a caller gets different
payloads depending on which path it is talking to — the divergence the
maintainer flagged in #36. Both now import payload_shaping, and these tests
assert they agree.
"""

import asyncio
import copy
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import payload_shaping as ps
import basecamp_fastmcp as bf
from mcp_server_cli import MCPServer


def run(coro):
    return asyncio.run(coro)


async def _fake_run_sync(func, *args, **kwargs):
    return func(*args, **kwargs)


PROJECT = {
    "id": 1, "name": "Acme", "status": "active", "purpose": "topic",
    "description": "d", "app_url": "https://app/1",
    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-02-01T00:00:00Z",
    "url": "https://api/1.json",
    "bookmark_url": "https://api/bm.json", "star_url": "https://api/star.json",
    "people": {"team": {"count": 1, "sample": [
        {"id": 9, "name": "Joe", "avatar_url": "https://cdn/a",
         "attachable_sgid": "BAh"}]}},
    "dock": [
        {"id": 11, "name": "todoset", "title": "To-dos", "enabled": True,
         "url": "https://api/ts.json", "app_url": "https://app/ts"},
        {"id": 12, "name": "chat", "title": "Chat", "enabled": False,
         "url": "https://api/c.json", "app_url": "https://app/c"},
    ],
}

TODO = {
    "id": 5, "title": "T", "content": "T", "type": "Todo", "completed": False,
    "due_on": "2026-02-01", "has_description": True, "description": "x" * 400,
    "app_url": "https://app/t/5", "bookmark_url": "https://api/bm.json",
    "bucket": {"id": 1, "name": "Acme", "type": "Project"},
    "assignees": [{"id": 9, "name": "Joe", "avatar_url": "https://cdn/a"}],
    "creator": {"id": 8, "name": "Ann", "avatar_url": "https://cdn/b",
                "email_address": "a@x.com", "attachable_sgid": "BAh"},
}


def _cli_with(**client_attrs):
    """An MCPServer whose client is a stub returning the given payloads.

    SimpleNamespace, not a class body: attributes set on a class become bound
    methods and would receive `self` as a positional argument.
    """
    return MCPServer(), SimpleNamespace(**client_attrs)


def project_listing(n):
    """`n` distinct projects — enough to make the default full cap bite.

    A single-project fixture cannot exercise a cap of 5: the assertions pass
    whether the cap is applied or removed entirely.
    """
    out = []
    for i in range(1, n + 1):
        p = copy.deepcopy(PROJECT)
        p["id"] = i
        p["name"] = "Acme" if i == 1 else f"Acme-{i}"
        p["status"] = "active" if i % 2 else "archived"
        p["app_url"] = f"https://app/{i}"
        out.append(p)
    return out


class TestProjectsParity(unittest.TestCase):

    # A literal, not FULL_DETAIL_DEFAULT_LIMIT + 2: deriving the fixture from
    # the constant makes the cap assertions tautological, since raising the
    # constant would grow the fixture to match.
    PROJECT_COUNT = 7

    def setUp(self):
        self.raw = project_listing(self.PROJECT_COUNT)

    def _fastmcp(self, **kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_projects.return_value = list(self.raw)
            with patch.object(bf, "_run_sync", _fake_run_sync):
                return run(bf.get_projects(**kwargs))

    def _cli(self, **args):
        server, client = _cli_with(get_projects=lambda: list(self.raw))
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            return server._execute_tool("get_projects", args)

    def _both(self, **kwargs):
        return self._fastmcp(**kwargs), self._cli(**kwargs)

    def _assert_identical(self, a, b, label):
        """Compare the whole response, not just the first record.

        Comparing only projects[0] and `detail` is what let the paths drift:
        the CLI was omitting `notice`, `total_before_filter` and the
        default-cap metadata while these tests passed.
        """
        self.assertEqual(a, b, f"{label}: responses differ between paths")

    def test_summary_responses_match(self):
        a, b = self._both()
        self._assert_identical(a, b, "summary")
        self.assertIn("notice", a)
        self.assertEqual(a["detail"], ps.SUMMARY)

    def test_full_responses_match(self):
        a, b = self._both(detail="full", limit=100)
        self._assert_identical(a, b, "full")
        self.assertNotIn("notice", a, "the summary notice must not leak into full")
        for p in a["projects"]:
            self.assertNotIn("bookmark_url", p)
            self.assertTrue(all("url" not in d for d in p["dock"]))

    def test_filtered_responses_match_including_envelope(self):
        for kwargs in ({"query": "acme"}, {"query": "zzz"},
                       {"status": "active"}, {"status": "archived"},
                       {"query": "acme", "limit": 2}):
            with self.subTest(**kwargs):
                a, b = self._both(**kwargs)
                self._assert_identical(a, b, str(kwargs))

    def test_total_before_filter_reported_on_both_paths(self):
        a, b = self._both(query="acme-3")
        self._assert_identical(a, b, "query=acme-3")
        self.assertEqual(a["count"], 1)
        self.assertEqual(a["total_before_filter"], self.PROJECT_COUNT)

    def test_documented_full_cap_is_five(self):
        """The docstrings and README promise 5; pin it so they stay true."""
        self.assertEqual(ps.FULL_DETAIL_DEFAULT_LIMIT, 5)

    def test_default_full_cap_metadata_matches(self):
        a, b = self._both(detail="full")
        self._assert_identical(a, b, "default full cap")
        self.assertEqual(a["count"], 5)
        self.assertEqual(a["matched"], self.PROJECT_COUNT)
        self.assertTrue(a["truncated"])
        self.assertIn("notice_limit", a)
        self.assertIn("5", a["notice_limit"])

    def test_explicit_limit_suppresses_the_cap_notice(self):
        a, b = self._both(detail="full", limit=2)
        self._assert_identical(a, b, "explicit limit")
        self.assertEqual(a["count"], 2)
        self.assertNotIn("notice_limit", a)

    def test_negative_limit_clamped_on_both_paths(self):
        a, b = self._both(limit=-1)
        self._assert_identical(a, b, "limit=-1")
        self.assertEqual(a["count"], 0)
        self.assertTrue(a["truncated"])

    def test_cli_rejects_a_non_integer_limit(self):
        """inputSchema is advisory in the hand-rolled CLI dispatch."""
        result = self._cli(limit="ten")
        self.assertEqual(result.get("error"), "Invalid argument")
        self.assertIn("limit", result["message"])
        self.assertNotIn("projects", result)


class TestTodosParity(unittest.TestCase):

    def _fastmcp(self, **kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_todos.return_value = [dict(TODO)]
            with patch.object(bf, "_run_sync", _fake_run_sync):
                return run(bf.get_todos(project_id="1", todolist_id="2", **kwargs))

    def _cli(self, **args):
        server, client = _cli_with(
            get_todos=lambda *a, **k: [dict(TODO)])
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            return server._execute_tool(
                "get_todos", dict(project_id="1", todolist_id="2", **args))

    def test_summary_shapes_match(self):
        a, b = self._fastmcp(), self._cli()
        self.assertEqual(a["todos"][0], b["todos"][0])
        self.assertNotIn("description", a["todos"][0])
        self.assertEqual(a["todos"][0]["creator"], {"id": 8, "name": "Ann"})

    def test_full_shapes_match(self):
        a, b = self._fastmcp(detail="full"), self._cli(detail="full")
        self.assertEqual(set(a["todos"][0]), set(b["todos"][0]))
        self.assertIn("description", a["todos"][0])


class TestEnvVarAffectsBothPaths(unittest.TestCase):
    """BASECAMP_MCP_FULL_RESPONSES must apply to the CLI as well."""

    def setUp(self):
        self._old = os.environ.get(ps.FULL_RESPONSES_ENV)

    def tearDown(self):
        if self._old is None:
            os.environ.pop(ps.FULL_RESPONSES_ENV, None)
        else:
            os.environ[ps.FULL_RESPONSES_ENV] = self._old

    def _both(self):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_projects.return_value = [dict(PROJECT)]
            with patch.object(bf, "_run_sync", _fake_run_sync):
                a = run(bf.get_projects())
        server, client = _cli_with(get_projects=lambda: [dict(PROJECT)])
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            b = server._execute_tool("get_projects", {})
        return a, b

    def test_env_unset_gives_summary_on_both(self):
        os.environ.pop(ps.FULL_RESPONSES_ENV, None)
        a, b = self._both()
        self.assertEqual(a["detail"], ps.SUMMARY)
        self.assertEqual(b["detail"], ps.SUMMARY)

    def test_env_set_gives_full_on_both(self):
        os.environ[ps.FULL_RESPONSES_ENV] = "1"
        a, b = self._both()
        self.assertEqual(a["detail"], ps.FULL)
        self.assertEqual(b["detail"], ps.FULL)
        self.assertIn("dock", a["projects"][0])
        self.assertIn("dock", b["projects"][0])

    def test_explicit_detail_overrides_env_on_both(self):
        os.environ[ps.FULL_RESPONSES_ENV] = "1"
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_projects.return_value = [dict(PROJECT)]
            with patch.object(bf, "_run_sync", _fake_run_sync):
                a = run(bf.get_projects(detail="summary"))
        server, client = _cli_with(get_projects=lambda: [dict(PROJECT)])
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            b = server._execute_tool("get_projects", {"detail": "summary"})
        self.assertEqual(a["detail"], ps.SUMMARY)
        self.assertEqual(b["detail"], ps.SUMMARY)


class TestCliSchemasDeclareDetail(unittest.TestCase):
    """A knob the handler honours but the schema hides is unusable."""

    SHAPED = ("get_projects", "get_todos", "get_comments", "get_cards",
              "get_columns", "get_card_table", "get_card_tables",
              "get_assignable_people")

    def setUp(self):
        self.tools = {t["name"]: t for t in MCPServer()._get_available_tools()}

    def test_shaped_cli_tools_are_registered(self):
        """Skipping an absent tool would let a rename pass silently."""
        absent = [n for n in self.SHAPED if n not in self.tools]
        self.assertEqual(absent, [],
                         f"shaped CLI tools are not registered: {absent}")

    def test_shaped_cli_tools_declare_detail(self):
        missing = [n for n in self.SHAPED
                   if "detail" not in self.tools[n]["inputSchema"]["properties"]]
        self.assertEqual(missing, [],
                         f"CLI schemas omit `detail`: {missing}")

    def test_get_projects_declares_its_filters(self):
        props = self.tools["get_projects"]["inputSchema"]["properties"]
        for name in ("query", "status", "limit"):
            self.assertIn(name, props, f"get_projects schema omits `{name}`")


if __name__ == "__main__":
    unittest.main()
