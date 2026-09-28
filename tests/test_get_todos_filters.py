#!/usr/bin/env python3
"""Tests for get_todos() completed/status filters.

By default the Basecamp to-dos endpoint returns only the active (incomplete)
to-dos. get_todos() exposes `completed` and `status` so callers can fetch
completed or archived/trashed to-dos as well, threading the corresponding
query params through to the paginated request.
See https://github.com/basecamp/bc3-api/blob/master/sections/todos.md.
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


ENDPOINT = 'buckets/1/todolists/2/todos.json'


class TestGetTodosFilters(unittest.TestCase):
    """get_todos() maps completed/status to the right query params."""

    def test_default_sends_no_filter_params(self):
        client = _client()
        with patch.object(client, 'get_all_pages', return_value=[]) as gap:
            client.get_todos('1', '2')
        gap.assert_called_once_with(ENDPOINT, params=None, error_label='todos')

    def test_completed_true_sends_completed_param(self):
        client = _client()
        with patch.object(client, 'get_all_pages', return_value=[]) as gap:
            client.get_todos('1', '2', completed=True)
        gap.assert_called_once_with(
            ENDPOINT, params={'completed': 'true'}, error_label='todos')

    def test_completed_false_is_treated_as_default(self):
        client = _client()
        with patch.object(client, 'get_all_pages', return_value=[]) as gap:
            client.get_todos('1', '2', completed=False)
        gap.assert_called_once_with(ENDPOINT, params=None, error_label='todos')

    def test_status_archived_sends_status_param(self):
        client = _client()
        with patch.object(client, 'get_all_pages', return_value=[]) as gap:
            client.get_todos('1', '2', status='archived')
        gap.assert_called_once_with(
            ENDPOINT, params={'status': 'archived'}, error_label='todos')

    def test_completed_and_status_combine(self):
        client = _client()
        with patch.object(client, 'get_all_pages', return_value=[]) as gap:
            client.get_todos('1', '2', completed=True, status='trashed')
        gap.assert_called_once_with(
            ENDPOINT,
            params={'completed': 'true', 'status': 'trashed'},
            error_label='todos')

    def test_invalid_status_raises_value_error(self):
        client = _client()
        with patch.object(client, 'get_all_pages', return_value=[]):
            with self.assertRaises(ValueError):
                client.get_todos('1', '2', status='bogus')


if __name__ == '__main__':
    unittest.main()
