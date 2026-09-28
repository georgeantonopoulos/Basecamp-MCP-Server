#!/usr/bin/env python3
"""Tests for to-do/card completion status handling.

Basecamp's completion endpoints return ``204 No Content`` on success (see
https://github.com/basecamp/bc3-api/blob/master/sections/todos.md), so the
completion helpers must treat 204 (and an empty body) as success rather than
raising. They also tolerate 200/201 with a JSON body.
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


def _response(status_code, text=''):
    """Build a mock ``requests`` response with the given status and body."""
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = {'id': 99, 'completed': True}
    return resp


class TestTodoCompletion(unittest.TestCase):
    """Completion helpers treat 200/201/204 as success."""

    def test_complete_todo_accepts_204_no_content(self):
        """204 with an empty body is success, not an error."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(204, '')) as posted:
            result = client.complete_todo('1', '2')
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get('status'), 'completed')
        self.assertEqual(result.get('todo_id'), '2')
        posted.assert_called_once()

    def test_complete_todo_accepts_200_empty_body(self):
        """200 with an empty body returns the synthesised completion dict."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(200, '')):
            result = client.complete_todo('1', '2')
        self.assertEqual(result.get('status'), 'completed')
        self.assertEqual(result.get('todo_id'), '2')

    def test_complete_todo_accepts_201_with_body(self):
        """A 201 with a JSON body still returns the parsed payload."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(201, '{"id": 99}')):
            result = client.complete_todo('1', '2')
        self.assertEqual(result.get('id'), 99)

    def test_complete_todo_raises_on_error_status(self):
        """A 4xx response raises with the status code in the message."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(403, 'Forbidden')):
            with self.assertRaisesRegex(Exception, '403'):
                client.complete_todo('1', '2')

    def test_complete_card_accepts_204(self):
        """complete_card returns the completion dict (with card_id) on 204."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(204, '')):
            result = client.complete_card('1', '2')
        self.assertEqual(result.get('status'), 'completed')
        self.assertEqual(result.get('card_id'), '2')

    def test_complete_card_accepts_200_empty_body(self):
        """complete_card also accepts a 200 with an empty body."""
        client = _client()
        with patch.object(client, 'post', return_value=_response(200, '')):
            result = client.complete_card('1', '2')
        self.assertEqual(result.get('status'), 'completed')
        self.assertEqual(result.get('card_id'), '2')


if __name__ == '__main__':
    unittest.main()
