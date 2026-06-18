#!/usr/bin/env python3
"""Tests for Basecamp card-step completion status handling."""

import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from basecamp_client import BasecampClient


def _client():
    """Return a BasecampClient with dummy OAuth credentials for unit tests."""
    return BasecampClient(
        access_token='token',
        account_id='123',
        user_agent='test-agent',
        auth_mode='oauth',
    )


def _response(status_code, text='{"id": 2, "completed": true}', payload=None):
    """Build a mock ``requests`` response with the given status and body."""
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = payload or {'id': 2, 'completed': True}
    return resp


class TestCardStepCompletion(unittest.TestCase):
    """Card steps use the documented card-table completions endpoint."""

    def test_complete_card_step_uses_completion_on(self):
        """Completion uses PUT with completion=on and returns the step JSON."""
        client = _client()
        with patch.object(client, 'put', return_value=_response(200)) as put:
            result = client.complete_card_step('1', '2')

        self.assertEqual(result.get('id'), 2)
        self.assertTrue(result.get('completed'))
        put.assert_called_once_with(
            'buckets/1/card_tables/steps/2/completions.json',
            {'completion': 'on'},
        )

    def test_uncomplete_card_step_uses_completion_off(self):
        """Uncompletion uses PUT with completion=off and returns the step JSON."""
        client = _client()
        with patch.object(
            client,
            'put',
            return_value=_response(200, payload={'id': 2, 'completed': False}),
        ) as put:
            result = client.uncomplete_card_step('1', '2')

        self.assertEqual(result.get('id'), 2)
        self.assertFalse(result.get('completed'))
        put.assert_called_once_with(
            'buckets/1/card_tables/steps/2/completions.json',
            {'completion': 'off'},
        )

    def test_complete_card_step_raises_on_error_status(self):
        """A non-200 response raises with the status code in the message."""
        client = _client()
        with patch.object(client, 'put', return_value=_response(404, 'Not Found')):
            with self.assertRaisesRegex(Exception, '404'):
                client.complete_card_step('1', '2')


if __name__ == '__main__':
    unittest.main()
