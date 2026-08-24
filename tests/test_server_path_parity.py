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

    def test_summary_responses_match(self):
        a, b = self._fastmcp(), self._cli()
        self.assertEqual(a, b, "todo responses differ between paths")
        self.assertNotIn("description", a["todos"][0])
        self.assertEqual(a["todos"][0]["creator"], {"id": 8, "name": "Ann"})

    def test_full_responses_match(self):
        a, b = self._fastmcp(detail="full"), self._cli(detail="full")
        self.assertEqual(a, b, "todo full responses differ between paths")
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
        self.assertEqual(a, b, "responses differ with the env var unset")
        self.assertEqual(a["detail"], ps.SUMMARY)

    def test_env_set_gives_full_on_both(self):
        os.environ[ps.FULL_RESPONSES_ENV] = "1"
        a, b = self._both()
        self.assertEqual(a, b, "responses differ with the env var set")
        self.assertEqual(a["detail"], ps.FULL)
        self.assertIn("dock", a["projects"][0])

    def test_explicit_detail_overrides_env_on_both(self):
        os.environ[ps.FULL_RESPONSES_ENV] = "1"
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_projects.return_value = [dict(PROJECT)]
            with patch.object(bf, "_run_sync", _fake_run_sync):
                a = run(bf.get_projects(detail="summary"))
        server, client = _cli_with(get_projects=lambda: [dict(PROJECT)])
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            b = server._execute_tool("get_projects", {"detail": "summary"})
        self.assertEqual(a, b,
                         "responses differ when detail overrides the env var")
        self.assertEqual(a["detail"], ps.SUMMARY)


class TestAssignablePeopleParity(unittest.TestCase):
    """The CLI copy had no `query`, no `company`, no `total_before_filter`."""

    PEOPLE = [
        {"id": 9, "name": "Joe West", "email_address": "joe@x.com",
         "title": "Dev", "avatar_url": "https://cdn/a",
         "attachable_sgid": "BAh",
         "company": {"id": 3, "name": "Acme Ltd"}},
        {"id": 10, "name": "Ann Blake", "email_address": "ann@y.com",
         "title": "PM", "avatar_url": "https://cdn/b",
         "company": {"id": 4, "name": "Beta Co"}},
    ]

    def _fastmcp(self, **kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_assignable_people.return_value = [
                dict(p) for p in self.PEOPLE]
            with patch.object(bf, "_run_sync", _fake_run_sync):
                return run(bf.get_assignable_people(**kwargs))

    def _cli(self, **args):
        server, client = _cli_with(
            get_assignable_people=lambda *a, **k: [dict(p) for p in self.PEOPLE])
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            return server._execute_tool("get_assignable_people", args)

    def test_summary_responses_match(self):
        a, b = self._fastmcp(), self._cli()
        self.assertEqual(a, b, "people responses differ between paths")
        self.assertEqual(a["count"], 2)
        self.assertNotIn("total_before_filter", a)

    def test_company_name_is_flattened_on_both_paths(self):
        a, b = self._fastmcp(), self._cli()
        self.assertEqual(a, b)
        self.assertEqual(a["people"][0]["company"], "Acme Ltd")
        self.assertNotIn("avatar_url", a["people"][0])

    def test_query_matches_on_both_paths(self):
        for q in ("joe", "JOE", "ann@y.com", "nobody"):
            with self.subTest(query=q):
                a, b = self._fastmcp(query=q), self._cli(query=q)
                self.assertEqual(a, b, f"query={q!r} differs between paths")

    def test_query_reports_total_before_filter(self):
        a, b = self._fastmcp(query="joe"), self._cli(query="joe")
        self.assertEqual(a, b)
        self.assertEqual(a["count"], 1)
        self.assertEqual(a["total_before_filter"], 2)

    def test_full_responses_match_and_prune(self):
        a, b = self._fastmcp(detail="full"), self._cli(detail="full")
        self.assertEqual(a, b)
        self.assertNotIn("avatar_url", a["people"][0])
        self.assertNotIn("attachable_sgid", a["people"][0])
        self.assertIsInstance(a["people"][0]["company"], dict)


OVERDUE_REPORT = {
    "under_a_week_late": [dict(TODO, id=101)],
    "over_a_week_late": [dict(TODO, id=102), dict(TODO, id=103,
                              assignees=[{"id": 77, "name": "Zoe"}])],
    "over_a_month_late": [],
    # A non-list bucket must survive rather than be dropped.
    "generated_at": "2026-08-24T00:00:00Z",
}

ASSIGNMENTS_REPORT = {
    "person": {"id": 8, "name": "Ann", "email_address": "a@x.com",
               "avatar_url": "https://cdn/b", "attachable_sgid": "BAh"},
    "grouped_by": "bucket",
    "todos": [dict(TODO, id=201), dict(TODO, id=202)],
}

COLUMN = {
    "id": 31, "title": "Doing", "type": "Kanban::Column",
    "cards_count": 2, "app_url": "https://app/col/31",
    "bookmark_url": "https://api/bm.json",
    "subscription_url": "https://api/sub.json",
    "creator": {"id": 8, "name": "Ann", "avatar_url": "https://cdn/b"},
}

CARD = {
    "id": 41, "title": "Ship it", "content": "<div>body</div>",
    "type": "Kanban::Card", "app_url": "https://app/card/41",
    "attachable_sgid": "BAh", "comments_url": "https://api/c.json",
    "assignees": [{"id": 9, "name": "Joe", "avatar_url": "https://cdn/a"}],
}


class TestOverdueTodosParity(unittest.TestCase):
    """The CLI returned the raw report — no shaping, no envelope at all."""

    def _fastmcp(self, **kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_overdue_todos.return_value = dict(OVERDUE_REPORT)
            with patch.object(bf, "_run_sync", _fake_run_sync):
                return run(bf.get_overdue_todos(**kwargs))

    def _cli(self, **args):
        server, client = _cli_with(
            get_overdue_todos=lambda *a, **k: dict(OVERDUE_REPORT))
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            return server._execute_tool("get_overdue_todos", args)

    def test_summary_responses_match(self):
        a, b = self._fastmcp(), self._cli()
        self.assertEqual(a, b, "overdue responses differ between paths")
        self.assertEqual(a["total"], 3)
        self.assertEqual(a["counts_by_group"],
                         {"under_a_week_late": 1, "over_a_week_late": 2,
                          "over_a_month_late": 0})
        self.assertEqual(a["scope"], "entire account")
        self.assertEqual(a["detail"], ps.SUMMARY)

    def test_full_responses_match(self):
        a, b = self._fastmcp(detail="full"), self._cli(detail="full")
        self.assertEqual(a, b)
        self.assertEqual(a["detail"], ps.FULL)

    def test_assignee_filter_matches_on_both_paths(self):
        a, b = self._fastmcp(assignee_id="77"), self._cli(assignee_id="77")
        self.assertEqual(a, b, "assignee filter differs between paths")
        self.assertEqual(a["total"], 1)
        self.assertEqual(a["scope"], "assignee 77")

    def test_non_list_bucket_is_preserved(self):
        a = self._fastmcp()
        self.assertEqual(a["overdue"]["generated_at"], "2026-08-24T00:00:00Z")
        self.assertNotIn("generated_at", a["counts_by_group"])

    def test_summary_drops_the_bulk(self):
        a = self._fastmcp()
        todo = a["overdue"]["under_a_week_late"][0]
        self.assertNotIn("description", todo)
        self.assertNotIn("bookmark_url", todo)
        self.assertEqual(todo["creator"], {"id": 8, "name": "Ann"})


class TestPersonAssignmentsParity(unittest.TestCase):
    """The CLI omitted `detail` and returned `person` unshaped."""

    def _fastmcp(self, **kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            gc.return_value.get_person_assignments.return_value = dict(
                ASSIGNMENTS_REPORT)
            with patch.object(bf, "_run_sync", _fake_run_sync):
                return run(bf.get_person_assignments(person_id="8", **kwargs))

    def _cli(self, **args):
        server, client = _cli_with(
            get_person_assignments=lambda *a, **k: dict(ASSIGNMENTS_REPORT))
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            return server._execute_tool(
                "get_person_assignments", dict(person_id="8", **args))

    def test_summary_responses_match(self):
        a, b = self._fastmcp(), self._cli()
        self.assertEqual(a, b, "assignment responses differ between paths")
        self.assertEqual(a["count"], 2)
        self.assertEqual(a["detail"], ps.SUMMARY)

    def test_full_responses_match(self):
        a, b = self._fastmcp(detail="full"), self._cli(detail="full")
        self.assertEqual(a, b)

    def test_person_is_reduced_to_id_and_name(self):
        a = self._fastmcp()
        self.assertEqual(a["person"], {"id": 8, "name": "Ann"})


class TestSingleRecordParity(unittest.TestCase):
    """get_project/get_column/get_card must shape identically on both paths."""

    def _pair(self, tool, payload, kwargs):
        with patch.object(bf, "_get_basecamp_client") as gc:
            getattr(gc.return_value, tool).return_value = dict(payload)
            with patch.object(bf, "_run_sync", _fake_run_sync):
                a = run(getattr(bf, tool)(**kwargs))
        server, client = _cli_with(**{tool: lambda *x, **k: dict(payload)})
        with patch.object(MCPServer, "_get_basecamp_client", return_value=client):
            b = server._execute_tool(tool, dict(kwargs))
        return a, b

    def test_get_column_matches_and_prunes(self):
        a, b = self._pair("get_column", COLUMN,
                          {"project_id": "1", "column_id": "31"})
        self.assertEqual(a, b, "get_column differs between paths")
        self.assertNotIn("bookmark_url", a["column"])
        self.assertNotIn("subscription_url", a["column"])
        self.assertNotIn("avatar_url", a["column"]["creator"])

    def test_get_card_matches_and_prunes(self):
        a, b = self._pair("get_card", CARD,
                          {"project_id": "1", "card_id": "41"})
        self.assertEqual(a, b, "get_card differs between paths")
        self.assertNotIn("attachable_sgid", a["card"])
        self.assertNotIn("comments_url", a["card"])

    def test_get_project_matches(self):
        a, b = self._pair("get_project", PROJECT, {"project_id": "1"})
        self.assertEqual(a, b, "get_project differs between paths")
        self.assertTrue(all("url" not in d for d in a["project"]["dock"]))


class TestShapingDoesNotMutateCallerData(unittest.TestCase):
    """The helpers return a value, so they must not edit their argument.

    get_project hands a caller-owned record straight to project_full; an
    in-place trim there would edit data the caller still holds.
    """

    def test_trim_dock_leaves_the_input_alone(self):
        original = copy.deepcopy(PROJECT)
        out = ps.trim_dock(original)
        self.assertEqual(original, PROJECT, "trim_dock mutated its argument")
        self.assertTrue(all("url" not in d for d in out["dock"]))

    def test_trim_people_sample_leaves_the_input_alone(self):
        original = copy.deepcopy(PROJECT)
        out = ps.trim_people_sample(original)
        self.assertEqual(original, PROJECT,
                         "trim_people_sample mutated its argument")
        self.assertEqual(out["people"]["team"]["sample"][0],
                         {"id": 9, "name": "Joe"})

    def test_project_full_leaves_the_input_alone(self):
        original = copy.deepcopy(PROJECT)
        ps.project_full(original)
        self.assertEqual(original, PROJECT, "project_full mutated its argument")

    def test_shape_card_table_leaves_the_input_alone(self):
        table = {"id": 1, "title": "Board", "lists": [dict(COLUMN)]}
        original = copy.deepcopy(table)
        ps.shape_card_table(table, ps.SUMMARY)
        self.assertEqual(table, original,
                         "shape_card_table mutated its argument")


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

    def test_get_assignable_people_declares_query(self):
        props = self.tools["get_assignable_people"]["inputSchema"]["properties"]
        self.assertIn("query", props)

    def test_get_overdue_todos_declares_its_knobs(self):
        props = self.tools["get_overdue_todos"]["inputSchema"]["properties"]
        for name in ("detail", "assignee_id"):
            self.assertIn(name, props,
                          f"get_overdue_todos schema omits `{name}`")

    def test_get_projects_declares_its_filters(self):
        props = self.tools["get_projects"]["inputSchema"]["properties"]
        for name in ("query", "status", "limit"):
            self.assertIn(name, props, f"get_projects schema omits `{name}`")


if __name__ == "__main__":
    unittest.main()
