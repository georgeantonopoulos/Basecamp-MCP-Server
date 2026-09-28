#!/usr/bin/env python3
"""Tests for the Reports API helpers.

Covers the three read-only report endpoints
(https://github.com/basecamp/bc-api/blob/master/sections/reports.md):

- ``get_assignable_people()`` — ``GET /reports/todos/assigned.json``
- ``get_person_assignments()`` — ``GET /reports/todos/assigned/{id}.json``,
  the cross-project per-person assignment report
- ``get_overdue_todos()`` — ``GET /reports/todos/overdue.json``

The per-person report returns a single JSON object (``person``,
``grouped_by``, ``todos``); if the API paginates the embedded ``todos``
list via the ``Link`` header, the pages must be merged into one report.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from basecamp_client import BasecampClient


def _client():
    """Return a BasecampClient with dummy OAuth credentials for unit tests."""
    return BasecampClient(
        access_token='token', account_id='123',
        user_agent='test-agent', auth_mode='oauth',
    )


def _response(payload, has_next=False, status_code=200, text=''):
    """Build a mock ``requests`` response for a report endpoint."""
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = payload
    resp.headers = {}
    if has_next:
        resp.headers['Link'] = (
            '<https://3.basecampapi.com/123/reports/todos/assigned/1.json'
            '?page=2>; rel="next"'
        )
    return resp


class TestGetAssignablePeople(unittest.TestCase):
    """get_assignable_people() lists everyone who can receive to-dos."""

    def test_uses_report_endpoint_and_aggregates_pages(self):
        """The report endpoint is paginated like other list endpoints."""
        client = _client()
        pages = [
            _response([{'id': i} for i in range(1, 16)], has_next=True),
            _response([{'id': 16}]),
        ]
        with patch.object(client, 'get', side_effect=pages) as got:
            result = client.get_assignable_people()
        self.assertEqual(len(result), 16)
        got.assert_any_call('reports/todos/assigned.json', params={'page': 1})


class TestGetPersonAssignments(unittest.TestCase):
    """get_person_assignments() returns one person's cross-project report."""

    def test_single_page_returns_report_object(self):
        """A single-page response is returned unchanged."""
        client = _client()
        report = {
            'person': {'id': 1, 'name': 'Amy Rivera'},
            'grouped_by': 'bucket',
            'todos': [{'id': 10}, {'id': 11}],
        }
        with patch.object(client, 'get',
                          return_value=_response(report)) as got:
            result = client.get_person_assignments('1')
        self.assertEqual(result, report)
        got.assert_called_once_with(
            'reports/todos/assigned/1.json', params=None)

    def test_group_by_is_passed_as_query_parameter(self):
        """group_by='date' reaches the API as a query parameter."""
        client = _client()
        report = {'person': {'id': 1}, 'grouped_by': 'date', 'todos': []}
        with patch.object(client, 'get',
                          return_value=_response(report)) as got:
            client.get_person_assignments('1', group_by='date')
        got.assert_called_once_with(
            'reports/todos/assigned/1.json', params={'group_by': 'date'})

    def test_paginated_todos_are_merged_into_one_report(self):
        """Link-header pagination merges todos while keeping the person."""
        client = _client()
        pages = [
            _response({'person': {'id': 1}, 'grouped_by': 'bucket',
                       'todos': [{'id': 10}]}, has_next=True),
            _response({'person': {'id': 1}, 'grouped_by': 'bucket',
                       'todos': [{'id': 11}]}),
        ]
        with patch.object(client, 'get', side_effect=pages) as got:
            result = client.get_person_assignments('1', group_by='bucket')
        self.assertEqual(result['person'], {'id': 1})
        self.assertEqual(result['todos'], [{'id': 10}, {'id': 11}])
        got.assert_any_call(
            'reports/todos/assigned/1.json',
            params={'group_by': 'bucket', 'page': 2})

    def test_error_status_raises(self):
        """Non-200 responses raise with status and body."""
        client = _client()
        resp = _response({}, status_code=404, text='not found')
        with patch.object(client, 'get', return_value=resp):
            with self.assertRaises(Exception) as ctx:
                client.get_person_assignments('999')
        self.assertEqual(
            str(ctx.exception),
            'Failed to get person assignments: 404 - not found')

    def test_persistent_next_page_hits_page_cap(self):
        """A response that always advertises a next page raises at MAX_PAGES."""
        client = _client()

        def fresh_page(*args, **kwargs):
            # A new response per call: reusing one mock would alias the
            # report dict across pages, which real requests never do.
            return _response({'person': {'id': 1}, 'todos': [{'id': 10}]},
                             has_next=True)

        with patch.object(client, 'get', side_effect=fresh_page) as got:
            with self.assertRaises(Exception) as ctx:
                client.get_person_assignments('1')
        self.assertIn('pagination exceeded', str(ctx.exception))
        self.assertEqual(got.call_count, BasecampClient.MAX_PAGES)


class TestGetOverdueTodos(unittest.TestCase):
    """get_overdue_todos() returns the lateness-grouped report."""

    def test_returns_lateness_groups(self):
        """The overdue report object is returned as-is."""
        client = _client()
        report = {
            'under_a_week_late': [{'id': 1}],
            'over_a_week_late': [],
            'over_a_month_late': [],
            'over_three_months_late': [],
        }
        with patch.object(client, 'get',
                          return_value=_response(report)) as got:
            result = client.get_overdue_todos()
        self.assertEqual(result, report)
        got.assert_called_once_with('reports/todos/overdue.json')

    def test_error_status_raises(self):
        """Non-200 responses raise with status and body."""
        client = _client()
        resp = _response({}, status_code=500, text='boom')
        with patch.object(client, 'get', return_value=resp):
            with self.assertRaises(Exception) as ctx:
                client.get_overdue_todos()
        self.assertEqual(
            str(ctx.exception), 'Failed to get overdue todos: 500 - boom')


if __name__ == '__main__':
    unittest.main()
