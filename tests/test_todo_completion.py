#!/usr/bin/env python3
"""Tests for to-do/card completion status handling.

Basecamp's completion endpoints return ``204 No Content`` on success (see
https://github.com/basecamp/bc3-api/blob/master/sections/todos.md), so the
completion helpers must treat 204 as success rather than raising.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from basecamp_client import BasecampClient


def _client():
    return BasecampClient(
        access_token='token', account_id='123',
        user_agent='test-agent', auth_mode='oauth',
    )


def _response(status_code, text=''):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = {'id': 99, 'completed': True}
    return resp


class TestTodoCompletion(unittest.TestCase):
    def test_complete_todo_accepts_204_no_content(self):
        """204 with an empty body is success, not an error."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(204, '')) as posted:
            result = client.complete_todo('1', '2')
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('status'), 'completed')
        self.assertEqual(result.get('todo_id'), '2')
        posted.assert_called_once()

    def test_complete_todo_accepts_201_with_body(self):
        """A 201 with a JSON body still returns the parsed payload."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(201, '{"id": 99}')):
            result = client.complete_todo('1', '2')
        self.assertEqual(result.get('id'), 99)

    def test_complete_todo_raises_on_error_status(self):
        client = _client()
        with patch.object(client, 'post', return_value=_response(403, 'Forbidden')):
            with self.assertRaises(Exception):
                client.complete_todo('1', '2')

    def test_complete_card_accepts_204(self):
        client = _client()
        with patch.object(client, 'post', return_value=_response(204, '')):
            result = client.complete_card('1', '2')
        self.assertEqual(result.get('status'), 'completed')

    def test_complete_card_step_accepts_204(self):
        client = _client()
        with patch.object(client, 'post', return_value=_response(204, '')):
            result = client.complete_card_step('1', '2')
        self.assertEqual(result.get('status'), 'completed')


if __name__ == '__main__':
    unittest.main()
