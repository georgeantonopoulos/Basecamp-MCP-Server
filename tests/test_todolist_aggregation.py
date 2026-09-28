#!/usr/bin/env python3
"""Tests for to-do list aggregation across multiple to-do sets.

Basecamp 3 normally gives a project a single todoset, but a project can carry
more than one "To-dos" tool in its dock. The default one is sometimes disabled
and empty while a second, enabled todoset holds the real lists, so selecting
the first dock entry silently returns nothing. ``get_todolists()`` must walk
every enabled todoset, paginate each one, and de-duplicate the result.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from basecamp_client import BasecampClient


def _client():
    """Return a BasecampClient with dummy OAuth credentials for unit tests."""
    return BasecampClient(
        access_token='token', account_id='123',
        user_agent='test-agent', auth_mode='oauth',
    )


def _todoset(todoset_id, enabled=True):
    """Build a project dock entry for a to-do set."""
    return {'name': 'todoset', 'id': todoset_id, 'enabled': enabled}


class TestGetTodosets(unittest.TestCase):
    """get_todosets() selects the to-do sets that actually hold lists."""

    def test_prefers_enabled_todosets(self):
        """A disabled default todoset is skipped in favour of an enabled one."""
        client = _client()
        disabled, enabled = _todoset(1, enabled=False), _todoset(2)
        project = {'dock': [disabled, {'name': 'schedule', 'id': 9}, enabled]}
        with patch.object(client, 'get_project', return_value=project):
            self.assertEqual(client.get_todosets('1'), [enabled])

    def test_returns_every_enabled_todoset(self):
        """Projects with several enabled To-dos tools return all of them."""
        client = _client()
        first, second = _todoset(1), _todoset(2)
        with patch.object(client, 'get_project',
                          return_value={'dock': [first, second]}):
            self.assertEqual(client.get_todosets('1'), [first, second])

    def test_falls_back_to_all_when_none_enabled(self):
        """Docks that never set `enabled` still yield their to-do sets."""
        client = _client()
        bare = {'name': 'todoset', 'id': 1}
        with patch.object(client, 'get_project', return_value={'dock': [bare]}):
            self.assertEqual(client.get_todosets('1'), [bare])

    def test_ignores_unusable_dock_entries(self):
        """Malformed dock data does not raise before the todoset is found."""
        client = _client()
        todoset = _todoset(1)
        project = {'dock': [None, 'nonsense', {}, todoset]}
        with patch.object(client, 'get_project', return_value=project):
            self.assertEqual(client.get_todosets('1'), [todoset])

    def test_reports_missing_todoset(self):
        """A dock with no to-do set raises the shared dock lookup error."""
        client = _client()
        for project in ({}, {'dock': None}, {'dock': []}, None):
            with self.subTest(project=project):
                with patch.object(client, 'get_project', return_value=project):
                    with self.assertRaisesRegex(
                            Exception, 'Failed to get todoset for project: 1'):
                        client.get_todosets('1')


class TestGetTodoset(unittest.TestCase):
    """get_todoset() picks one target for single-todoset operations."""

    def test_returns_first_enabled_todoset(self):
        """The disabled default is not chosen as the creation target."""
        client = _client()
        disabled, enabled = _todoset(1, enabled=False), _todoset(2)
        with patch.object(client, 'get_project',
                          return_value={'dock': [disabled, enabled]}):
            self.assertEqual(client.get_todoset('1'), enabled)


class TestGetTodolists(unittest.TestCase):
    """get_todolists() aggregates paginated lists across every to-do set."""

    def test_aggregates_across_todosets(self):
        """Lists from each enabled todoset are combined in dock order."""
        client = _client()
        pages = [[{'id': 10}, {'id': 11}], [{'id': 20}]]
        with patch.object(client, 'get_todosets',
                          return_value=[_todoset(1), _todoset(2)]):
            with patch.object(client, 'get_all_pages', side_effect=pages):
                result = client.get_todolists('1')
        self.assertEqual(result, [{'id': 10}, {'id': 11}, {'id': 20}])

    def test_paginates_each_todoset(self):
        """Each todoset is fetched through the shared pagination helper."""
        client = _client()
        with patch.object(client, 'get_todosets',
                          return_value=[_todoset(1), _todoset(2)]):
            with patch.object(client, 'get_all_pages',
                              side_effect=[[], []]) as get_all_pages:
                client.get_todolists('99')
        self.assertEqual(get_all_pages.call_count, 2)
        get_all_pages.assert_any_call(
            'buckets/99/todosets/1/todolists.json', error_label='todolists')
        get_all_pages.assert_any_call(
            'buckets/99/todosets/2/todolists.json', error_label='todolists')

    def test_deduplicates_lists_by_id(self):
        """A todoset appearing twice in the dock does not duplicate lists."""
        client = _client()
        shared = {'id': 10, 'name': 'Shared'}
        with patch.object(client, 'get_todosets',
                          return_value=[_todoset(1), _todoset(1)]):
            with patch.object(client, 'get_all_pages',
                              side_effect=[[shared], [shared, {'id': 11}]]):
                result = client.get_todolists('1')
        self.assertEqual(result, [shared, {'id': 11}])

    def test_returns_lists_from_enabled_todoset_only(self):
        """An empty disabled todoset does not mask the enabled one's lists.

        This is the regression the aggregation exists for: selecting the first
        dock entry would return [] for these projects.
        """
        client = _client()
        project = {'dock': [_todoset(1, enabled=False), _todoset(2)]}
        with patch.object(client, 'get_project', return_value=project):
            with patch.object(client, 'get_all_pages',
                              return_value=[{'id': 20}]) as get_all_pages:
                result = client.get_todolists('1')
        self.assertEqual(result, [{'id': 20}])
        get_all_pages.assert_called_once_with(
            'buckets/1/todosets/2/todolists.json', error_label='todolists')


if __name__ == '__main__':
    unittest.main()
