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


# Launchpad (https://launchpad.37signals.com/authorization.json) lists every
# 37signals product a login can reach. Only "bc3" accounts (Basecamp 3 and 4)
# work with this server; the others are named so users recognise them.
PRODUCT_NAMES = {
    "bc3": "Basecamp 3 or 4",
    "bcx": "Basecamp 2",
    "basecamp": "Basecamp Classic",
    "campfire": "Campfire",
    "highrise": "Highrise",
    "backpack": "Backpack",
}

LAUNCHPAD_URL = "https://launchpad.37signals.com"


def basecamp_accounts(identity):
    """The Basecamp 3/4 accounts in a Launchpad authorization response."""
    return [a for a in (identity or {}).get("accounts") or [] if a.get("product") == "bc3"]


def _retry_hint():
    command = _login_command()
    if command:
        return f"run `{command}` again"
    return "sign in again at http://localhost:8000"


def _switch_login_hint():
    return (
        f"To fix it: open {LAUNCHPAD_URL} and sign out, then {_retry_hint()} and sign in with the "
        "email you use for Basecamp."
    )


def no_basecamp_account(identity=None):
    """Explain a login that reaches no Basecamp 3/4 account, and what to do about it."""
    identity = identity or {}
    email = (identity.get("identity") or {}).get("email_address")
    who = f"The 37signals login {email}" if email else "This 37signals login"
    others = sorted(
        {
            PRODUCT_NAMES.get(a.get("product"), a.get("product") or "an unknown product")
            for a in identity.get("accounts") or []
            if a.get("product") != "bc3"
        }
    )
    found = f" It only has access to: {', '.join(others)}." if others else ""
    return (
        f"{who} isn't a member of any Basecamp 3 or 4 account, so there is nothing to connect to.{found} "
        f"This server works with Basecamp 3 and 4 only. {_switch_login_hint()} "
        "If you don't have a Basecamp account yet, ask someone in your company to invite you, "
        "or start one at https://basecamp.com."
    )


def account_not_available(account_id, identity=None):
    """The saved account is no longer among the login's Basecamp accounts."""
    accounts = basecamp_accounts(identity)
    if not accounts:
        return no_basecamp_account(identity)
    names = ", ".join(f"{a.get('name')} (id {a.get('id')})" for a in accounts)
    return (
        f"This login can no longer open Basecamp account {account_id}: you may have been removed from it, "
        f"or the account was cancelled. Accounts this login can use: {names}. To switch, {_retry_hint()}."
    )


def no_account_selected():
    """A token is saved but no Basecamp account was chosen at sign-in."""
    return (
        "You're signed in, but no Basecamp account is selected, usually because that login has no "
        f"Basecamp 3 or 4 account. {_switch_login_hint()}"
    )


def auth_problem(token, is_expired):
    """(error, message) explaining why no Basecamp client could be built from ``token``."""
    has_token = bool(token and token.get("access_token"))
    if has_token and is_expired:
        return "OAuth token expired", expired()
    if has_token and not (token.get("account_id") or os.environ.get("BASECAMP_ACCOUNT_ID")):
        return "No Basecamp account", no_account_selected()
    return "Authentication required", sign_in_required()
