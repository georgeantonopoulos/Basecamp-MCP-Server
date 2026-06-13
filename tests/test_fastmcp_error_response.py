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

    assert response["status"] == "error"
    assert response["error"] == "Authentication required"
    assert "message" in response
