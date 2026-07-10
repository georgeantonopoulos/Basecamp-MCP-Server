#!/usr/bin/env python3
"""Tests for safe Basecamp project dock lookups."""

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from basecamp_client import BasecampClient


def _client():
    """Return a client with dummy OAuth credentials."""
    return BasecampClient(
        access_token='token', account_id='123',
        user_agent='test-agent', auth_mode='oauth',
    )


class TestDockLookup(unittest.TestCase):
    """Dock-backed helpers handle missing and malformed project data."""

    def test_find_dock_item_returns_named_item(self):
        client = _client()
        project = {
            'dock': [
                {'name': 'todoset', 'id': 1},
                {},
                {'name': 'schedule', 'id': 2},
            ],
        }
        self.assertEqual(
            client._find_dock_item(project, 'schedule'),
            {'name': 'schedule', 'id': 2},
        )

    def test_find_dock_item_returns_none_for_unusable_data(self):
        client = _client()
        projects = (
            None,
            {},
            {'dock': None},
            {'dock': []},
            {'dock': [{}]},
        )
        for project in projects:
            with self.subTest(project=project):
                self.assertIsNone(client._find_dock_item(project, 'schedule'))

    def test_get_todoset_reports_missing_dock(self):
        client = _client()
        with patch.object(client, 'get_project', return_value={}):
            with self.assertRaisesRegex(Exception, 'Failed to get todoset for project: 1') as ctx:
                client.get_todoset('1')
        self.assertEqual(str(ctx.exception), 'Failed to get todoset for project: 1')

    def test_get_todoset_returns_named_dock_item(self):
        client = _client()
        todoset = {'name': 'todoset', 'id': 42}
        with patch.object(
                client, 'get_project', return_value={'dock': [todoset]}):
            self.assertEqual(client.get_todoset('1'), todoset)

    def test_get_message_board_reports_missing_dock(self):
        client = _client()
        with patch.object(client, 'get_project', return_value={}):
            with self.assertRaisesRegex(
                    Exception, 'No message board found for project: 1'):
                client.get_message_board('1')

    def test_get_message_board_uses_named_dock_item(self):
        client = _client()
        response = Mock(status_code=200)
        response.json.return_value = {'id': 42}
        project = {'dock': [{'name': 'message_board', 'id': 42}]}
        with patch.object(client, 'get_project', return_value=project), \
                patch.object(client, 'get', return_value=response) as get:
            result = client.get_message_board('1')
        self.assertEqual(result, {'id': 42})
        get.assert_called_once_with('buckets/1/message_boards/42.json')

    def test_get_inbox_reports_missing_dock(self):
        client = _client()
        with patch.object(client, 'get_project', return_value={}):
            with self.assertRaisesRegex(
                    Exception, 'No inbox found for project: 1'):
                client.get_inbox('1')

    def test_get_inbox_uses_named_dock_item(self):
        client = _client()
        response = Mock(status_code=200)
        response.json.return_value = {'id': 42}
        project = {'dock': [{'name': 'inbox', 'id': 42}]}
        with patch.object(client, 'get_project', return_value=project), \
                patch.object(client, 'get', return_value=response) as get:
            result = client.get_inbox('1')
        self.assertEqual(result, {'id': 42})
        get.assert_called_once_with('buckets/1/inboxes/42.json')

    def test_get_schedule_entries_returns_empty_for_missing_dock(self):
        client = _client()
        with patch.object(client, 'get_project', return_value={}), \
                patch.object(client, 'get_all_pages', Mock()) as get_all_pages:
            result = client.get_schedule_entries('1')
        self.assertEqual(result, [])
        get_all_pages.assert_not_called()

    def test_get_schedule_entries_uses_named_dock_item(self):
        client = _client()
        project = {'dock': [{'name': 'schedule', 'id': 42}]}
        with patch.object(client, 'get_project', return_value=project), \
                patch.object(client, 'get_all_pages', return_value=[{'id': 1}]) as get_all_pages:
            result = client.get_schedule_entries('1')
        self.assertEqual(result, [{'id': 1}])
        get_all_pages.assert_called_once_with(
            'buckets/1/schedules/42/entries.json',
            error_label='schedule entries',
        )


if __name__ == '__main__':
    unittest.main()
