"""Smoke-test an installed basecamp-mcp-server the way an MCP client launches it.

Usage: python scripts/smoke_installed.py <command> [args...]
e.g.   python scripts/smoke_installed.py uvx --from dist/x.whl basecamp-mcp-server

Checks the MCP handshake, that the four discovery tools are listed, that a
tool call without a sign-in returns a clear "run login" message, and that
nothing but JSON-RPC is written to stdout.
"""

import json
import subprocess
import sys
import tempfile
import os


def main(command):
    env = dict(os.environ, BASECAMP_MCP_HOME=tempfile.mkdtemp())
    for key in ("BASECAMP_CLIENT_ID", "BASECAMP_CLIENT_SECRET", "BASECAMP_MCP_TOKEN_FILE"):
        env.pop(key, None)
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, env=env,
    )

    def send(message):
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def receive(expected_id):
        while True:
            line = proc.stdout.readline()
            if not line:
                raise SystemExit(f"server exited before answering request {expected_id}")
            message = json.loads(line)  # any non-JSON stdout line fails here
            if message.get("id") == expected_id:
                return message

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "smoke", "version": "1"}}})
    print("server:", receive(1)["result"]["serverInfo"])
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = sorted(t["name"] for t in receive(2)["result"]["tools"])
    print("tools:", names)
    assert names == sorted([
        "list_basecamp_categories", "discover_basecamp_tools",
        "call_basecamp_read_tool", "call_basecamp_write_tool",
    ]), names

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
        "name": "call_basecamp_read_tool",
        "arguments": {"name": "get_projects", "arguments": {}}}})
    text = json.dumps(receive(3))
    print("unsigned call:", text[:200])
    assert "basecamp-mcp-server login" in text, "expected a pointer to the login command"

    proc.stdin.close()
    proc.wait(timeout=30)
    print("OK")


if __name__ == "__main__":
    main(sys.argv[1:])
