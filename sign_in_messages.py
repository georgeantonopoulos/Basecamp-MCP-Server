"""User-facing sign-in instructions, defined once for every server path.

A git checkout signs in through the local web page started by ``oauth_app.py``.
The installed package signs in with its ``login`` command and sets
``BASECAMP_MCP_LOGIN_COMMAND`` so these messages point users there instead.
"""

import os


def _login_command():
    return os.environ.get("BASECAMP_MCP_LOGIN_COMMAND", "").strip()


def _reauth_hint():
    command = _login_command()
    if command:
        return f"running `{command}`"
    return "visiting http://localhost:8000 and completing the OAuth flow again"


def expired_during_call():
    return (
        "Your Basecamp OAuth token expired during the API call. "
        f"Please re-authenticate by {_reauth_hint()}."
    )


def expired():
    return f"Your Basecamp OAuth token has expired. Please re-authenticate by {_reauth_hint()}."


def sign_in_required():
    command = _login_command()
    if command:
        return f"Please authenticate with Basecamp first. Run `{command}` to sign in."
    return "Please authenticate with Basecamp first. Visit http://localhost:8000 to log in."
