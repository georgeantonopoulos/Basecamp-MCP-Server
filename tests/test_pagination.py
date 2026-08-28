#!/usr/bin/env python3
"""Tests for list endpoint pagination.

Basecamp paginates all list endpoints (commonly 15 items per page) and
advertises further pages via the HTTP ``Link`` header (see
https://github.com/basecamp/bc3-api#pagination). ``get_all_pages()`` must
follow ``rel="next"`` links and aggregate every page, so list helpers such
as ``get_projects()`` return the full collection instead of only the first
15 items.
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


def _page(items, has_next=False):
    """Build a mock ``requests`` response for one page of a list endpoint."""
    resp = Mock()
    resp.status_code = 200
    resp.text = ''
    resp.json.return_value = items
    resp.headers = {}
    if has_next:
        resp.headers['Link'] = (
            '<https://3.basecampapi.com/123/projects.json?page=2>; rel="next"'
        )
    return resp


class TestGetAllPages(unittest.TestCase):
    """get_all_pages() follows Link headers and aggregates all pages."""

    def test_single_page_without_link_header(self):
        """A single page without a Link header is returned as-is."""
        client = _client()
        with patch.object(client, 'get', return_value=_page([{'id': 1}])) as got:
            result = client.get_all_pages('projects.json')
        self.assertEqual(result, [{'id': 1}])
        got.assert_called_once_with('projects.json', params={'page': 1})

    def test_multiple_pages_are_aggregated(self):
        """Pages are fetched until no rel="next" link remains."""
        client = _client()
        pages = [
            _page([{'id': i} for i in range(1, 16)], has_next=True),
            _page([{'id': i} for i in range(16, 31)], has_next=True),
            _page([{'id': i} for i in range(31, 45)]),
        ]
        with patch.object(client, 'get', side_effect=pages) as got:
            result = client.get_all_pages('projects.json')
        self.assertEqual(len(result), 44)
        self.assertEqual(got.call_count, 3)
        got.assert_any_call('projects.json', params={'page': 3})

    def test_empty_page_stops_iteration(self):
        """An empty page ends pagination even if a Link header is present."""
        client = _client()
        with patch.object(client, 'get', return_value=_page([], has_next=True)):
            result = client.get_all_pages('projects.json')
        self.assertEqual(result, [])

    def test_error_status_raises_with_label(self):
        """Non-200 responses raise an exception using the error label."""
        client = _client()
        resp = Mock()
        resp.status_code = 401
        resp.text = 'unauthorized'
        with patch.object(client, 'get', return_value=resp):
            with self.assertRaises(Exception) as ctx:
                client.get_all_pages('projects.json', error_label='projects')
        self.assertEqual(
            str(ctx.exception), 'Failed to get projects: 401 - unauthorized')

    def test_persistent_next_page_hits_page_cap(self):
        """A response that always advertises a next page raises at MAX_PAGES."""
        client = _client()
        with patch.object(
                client, 'get',
                return_value=_page([{'id': 1}], has_next=True)) as got:
            with self.assertRaises(Exception) as ctx:
                client.get_all_pages('projects.json', error_label='projects')
        self.assertIn('pagination exceeded', str(ctx.exception))
        self.assertEqual(got.call_count, BasecampClient.MAX_PAGES)

    def test_extra_params_are_preserved_across_pages(self):
        """Caller-supplied query params are kept on every page request."""
        client = _client()
        pages = [_page([{'id': 1}], has_next=True), _page([{'id': 2}])]
        with patch.object(client, 'get', side_effect=pages) as got:
            client.get_all_pages('projects.json', params={'status': 'archived'})
        got.assert_any_call('projects.json', params={'status': 'archived', 'page': 1})
        got.assert_any_call('projects.json', params={'status': 'archived', 'page': 2})


class TestListEndpointsPaginate(unittest.TestCase):
    """List helpers fetch all pages instead of only the first 15 items."""

    def test_get_projects_returns_all_pages(self):
        """get_projects() aggregates beyond the first page of 15 projects."""
        client = _client()
        pages = [
            _page([{'id': i} for i in range(1, 16)], has_next=True),
            _page([{'id': i} for i in range(16, 21)]),
        ]
        with patch.object(client, 'get', side_effect=pages):
            result = client.get_projects()
        self.assertEqual(len(result), 20)

    def test_get_people_returns_all_pages(self):
        """get_people() aggregates beyond the first page."""
        client = _client()
        pages = [
            _page([{'id': i} for i in range(1, 16)], has_next=True),
            _page([{'id': 16}]),
        ]
        with patch.object(client, 'get', side_effect=pages):
            result = client.get_people()
        self.assertEqual(len(result), 16)

    def test_get_cards_returns_all_pages(self):
        """get_cards() aggregates beyond the first page."""
        client = _client()
        pages = [
            _page([{'id': i} for i in range(1, 16)], has_next=True),
            _page([{'id': 16}]),
        ]
        with patch.object(client, 'get', side_effect=pages):
            result = client.get_cards('1', '2')
        self.assertEqual(len(result), 16)

    def test_get_schedule_entries_uses_dock_schedule(self):
        """get_schedule_entries() resolves the schedule from the project dock."""
        client = _client()
        entries = [{'id': 1}, {'id': 2}]
        with patch.object(client, 'get_project',
                          return_value={'dock': [{'name': 'schedule', 'id': 42}]}), \
                patch.object(client, 'get_all_pages',
                             return_value=entries) as get_all_pages:
            result = client.get_schedule_entries('1')
        self.assertEqual(result, entries)
        get_all_pages.assert_called_once_with(
            'buckets/1/schedules/42/entries.json',
            error_label='schedule entries')


if __name__ == '__main__':
    unittest.main()
