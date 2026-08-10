#!/usr/bin/env python3
"""The two server paths must return the same shapes for the same tool.

basecamp_fastmcp.py and mcp_server_cli.py are separate implementations over the
same client. If only one of them shapes its responses, a caller gets different
payloads depending on which path it is talking to — the divergence the
maintainer flagged in #36. Both now import payload_shaping, and these tests
assert they agree.
"""

import asyncio
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


class TestProjectsParity(unittest.TestCase):

    def _fastmcp(self, **kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_projects.return_value = [dict(PROJECT)]
            with patch.object(bf, "_run_sync", _fake_run_sync):
                return run(bf.get_projects(**kwargs))

    def _cli(self, **args):
        server, client = _cli_with(get_projects=lambda: [dict(PROJECT)])
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            return server._execute_tool("get_projects", args)

    def test_summary_shapes_match(self):
        a, b = self._fastmcp(), self._cli()
        self.assertEqual(set(a["projects"][0]), set(b["projects"][0]))
        self.assertEqual(a["projects"][0], b["projects"][0])
        self.assertEqual(a["detail"], b["detail"], "detail label differs")

    def test_full_shapes_match(self):
        a = self._fastmcp(detail="full")
        b = self._cli(detail="full")
        self.assertEqual(set(a["projects"][0]), set(b["projects"][0]))
        for p in (a["projects"][0], b["projects"][0]):
            self.assertNotIn("bookmark_url", p)
            self.assertTrue(all("url" not in d for d in p["dock"]))

    def test_query_filter_matches(self):
        self.assertEqual(len(self._fastmcp(query="acme")["projects"]),
                         len(self._cli(query="acme")["projects"]))
        self.assertEqual(len(self._fastmcp(query="zzz")["projects"]),
                         len(self._cli(query="zzz")["projects"]))

    def test_negative_limit_clamped_on_both_paths(self):
        a, b = self._fastmcp(limit=-1), self._cli(limit=-1)
        self.assertEqual(a["count"], 0)
        self.assertEqual(b["count"], 0)
        self.assertTrue(a.get("truncated") and b.get("truncated"))


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

    def test_shaped_cli_tools_declare_detail(self):
        tools = {t["name"]: t for t in MCPServer()._get_available_tools()}
        shaped = ["get_projects", "get_todos", "get_comments", "get_cards",
                  "get_columns", "get_card_table", "get_card_tables",
                  "get_assignable_people"]
        missing = [n for n in shaped
                   if n in tools
                   and "detail" not in tools[n]["inputSchema"]["properties"]]
        self.assertEqual(missing, [],
                         f"CLI schemas omit `detail`: {missing}")


if __name__ == "__main__":
    unittest.main()
