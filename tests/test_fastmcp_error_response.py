import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import basecamp_fastmcp


def test_error_response_includes_status_error():
    response = basecamp_fastmcp._error_response("Execution error", "boom")

    assert response == {
        "status": "error",
        "error": "Execution error",
        "message": "boom",
    }


@patch("basecamp_fastmcp.token_storage.is_token_expired", return_value=False)
def test_auth_error_response_includes_status_error(mock_is_expired):
    response = basecamp_fastmcp._get_auth_error_response()

    assert response == {
        "status": "error",
        "error": "Authentication required",
        "message": "Please authenticate with Basecamp first. Visit http://localhost:8000 to log in.",
    }


@patch("basecamp_fastmcp.token_storage.is_token_expired", return_value=True)
def test_expired_auth_error_response_includes_status_error(mock_is_expired):
    response = basecamp_fastmcp._get_auth_error_response()

    assert response == {
        "status": "error",
        "error": "OAuth token expired",
        "message": "Your Basecamp OAuth token has expired. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
    }
