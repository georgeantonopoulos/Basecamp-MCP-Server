#!/usr/bin/env python3
"""Guards against docstring/implementation drift in the MCP tool surface.

For an MCP server the docstring is the interface: it is the only thing the
calling model sees when deciding which tool to call and what it will cost. A
docstring that promises a cheap summary while the code returns the full record
actively misleads the caller into blowing its context budget, and nothing in a
normal test suite catches it.

These tests assert that:
  * every parameter documented in an Args: block actually exists,
  * every signature parameter is documented,
  * a default asserted in prose matches the real default,
  * the summary key sets promised by the shaped tools match what they return.
"""

import inspect
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import basecamp_fastmcp as bf

TOOLS = bf.mcp._tool_manager._tools


def _tool_fn(tool):
    return getattr(tool, "fn", None) or getattr(tool, "func", None)


def _documented_args(doc):
    """Parameter names listed under an Args: block."""
    if not doc:
        return []
    m = re.search(
        r"\n\s*Args:\s*\n(.*?)(\n\s*(Returns|Raises|Note|Example)s?:|\Z)", doc, re.S)
    if not m:
        return []
    return re.findall(r"^\s{4,}(\w+)\s*[:(]", m.group(1), re.M)


def _prose_default(doc, param):
    """A default asserted in prose, e.g. detail="summary" (the default)."""
    m = re.search(rf'{param}\s*=\s*"([^"]+)"\s*\((?:the\s+)?default\)', doc or "")
    return m.group(1) if m else None


class TestDocstringMatchesSignature(unittest.TestCase):

    def test_documented_params_exist(self):
        """An Args: entry naming a parameter the code doesn't accept."""
        bad = []
        for name, tool in TOOLS.items():
            fn = _tool_fn(tool)
            if fn is None:
                continue
            params = inspect.signature(fn).parameters
            for arg in _documented_args(inspect.getdoc(fn)):
                if arg not in params:
                    bad.append(f"{name}: documents '{arg}', not in signature")
        self.assertEqual(bad, [], "docstring promises parameters that don't exist:\n"
                                 + "\n".join(bad))

    def test_all_params_documented(self):
        """A parameter the caller can pass but the docstring never mentions."""
        bad = []
        for name, tool in TOOLS.items():
            fn = _tool_fn(tool)
            if fn is None:
                continue
            doc = inspect.getdoc(fn) or ""
            documented = set(_documented_args(doc))
            for p in inspect.signature(fn).parameters:
                if p not in documented:
                    bad.append(f"{name}: param '{p}' undocumented")
        self.assertEqual(bad, [], "undocumented parameters:\n" + "\n".join(bad))

    def test_prose_defaults_match_signature(self):
        """A default stated in prose that disagrees with the real default."""
        bad = []
        for name, tool in TOOLS.items():
            fn = _tool_fn(tool)
            if fn is None:
                continue
            doc = inspect.getdoc(fn) or ""
            for p, spec in inspect.signature(fn).parameters.items():
                claimed = _prose_default(doc, p)
                if claimed is None or spec.default is inspect._empty:
                    continue
                if str(spec.default) != claimed:
                    bad.append(
                        f"{name}: docstring says {p}='{claimed}' is the default, "
                        f"actual default is {spec.default!r}")
        self.assertEqual(bad, [], "documented defaults disagree with code:\n"
                                  + "\n".join(bad))


class TestSummaryShapeMatchesDocstring(unittest.TestCase):
    """The promised summary field lists must match what the code projects.

    This is the specific drift that caused the original problem: the
    get_projects docstring described an id/name/status/purpose/description/
    app_url summary while the implementation returned the full record.
    """

    def test_project_summary_keys_match_docstring(self):
        doc = inspect.getdoc(_tool_fn(TOOLS["get_projects"])) or ""
        m = re.search(r'detail="summary".*?returns only\s+(.*?)\s*—', doc, re.S)
        self.assertIsNotNone(m, "get_projects docstring no longer states its summary fields")
        named = {w.strip(" `.,\n\t") for w in re.split(r",|\band\b", m.group(1))
                 if w.strip(" `.,\n\t")}
        self.assertEqual(
            named, set(bf._PROJECT_SUMMARY_KEYS),
            "docstring's summary field list differs from _PROJECT_SUMMARY_KEYS")

    def test_project_summary_projection_returns_only_those_keys(self):
        fat = {k: k for k in list(bf._PROJECT_SUMMARY_KEYS) + [
            "people", "dock", "bookmark_url", "star_url", "url", "created_at"]}
        self.assertEqual(set(bf._project_summary(fat)), set(bf._PROJECT_SUMMARY_KEYS))

    def test_full_detail_default_limit_is_documented(self):
        doc = inspect.getdoc(_tool_fn(TOOLS["get_projects"])) or ""
        m = re.search(r"capped at (\d+) projects", doc)
        self.assertIsNotNone(m, "the detail='full' cap is no longer documented")
        self.assertEqual(int(m.group(1)), bf._FULL_DETAIL_DEFAULT_LIMIT)

    def test_noise_keys_never_survive_a_summary(self):
        for key in ("avatar_url", "bookmark_url", "star_url", "attachable_sgid"):
            self.assertIn(key, bf._NOISE_KEYS)


if __name__ == "__main__":
    unittest.main()
