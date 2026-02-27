#!/usr/bin/env python3
"""
Generate Codex MCP configuration for Basecamp MCP integration.

This script is path-agnostic: it derives all paths from its own location,
so it works regardless of where this repository is installed.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback used when python-dotenv is missing
    load_dotenv = None


def get_project_root() -> Path:
    """Get the absolute path to the project root."""
    return Path(__file__).resolve().parent


def get_python_path(project_root: Path) -> Path:
    """Get the Python executable path from virtual environment."""
    if platform.system() == "Windows":
        return project_root / "venv" / "Scripts" / "python.exe"
    return project_root / "venv" / "bin" / "python"


def get_server_details(project_root: Path, use_legacy: bool) -> tuple[str, Path, str]:
    """Return server name, script path, and human-readable label."""
    if use_legacy:
        return (
            "basecamp-legacy",
            project_root / "mcp_server_cli.py",
            "Legacy JSON-RPC server (mcp_server_cli.py)",
        )
    return (
        "basecamp",
        project_root / "basecamp_fastmcp.py",
        "FastMCP server (basecamp_fastmcp.py)",
    )


def load_env_vars(project_root: Path) -> dict[str, str]:
    """Load environment values for MCP server process."""
    dotenv_path = project_root / ".env"
    if load_dotenv is not None:
        load_dotenv(dotenv_path)
    elif dotenv_path.exists():
        # Lightweight fallback parser for KEY=VALUE lines.
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value

    env_vars = {
        "PYTHONPATH": str(project_root),
        "VIRTUAL_ENV": str(project_root / "venv"),
    }

    account_id = os.getenv("BASECAMP_ACCOUNT_ID")
    if account_id:
        env_vars["BASECAMP_ACCOUNT_ID"] = account_id
    else:
        print("WARNING: BASECAMP_ACCOUNT_ID was not found in .env")
        print(f"         Expected .env path: {dotenv_path}")
        print("         The server may fail for account-scoped endpoints.")

    return env_vars


def build_codex_add_command(
    server_name: str, python_path: Path, server_script: Path, env_vars: dict[str, str]
) -> list[str]:
    """Build `codex mcp add` command."""
    command = ["codex", "mcp", "add", server_name]
    for key, value in env_vars.items():
        command.extend(["--env", f"{key}={value}"])
    command.extend(["--", str(python_path), str(server_script)])
    return command


def run_command(command: list[str], check: bool) -> subprocess.CompletedProcess:
    """Run a subprocess command and return result."""
    return subprocess.run(command, check=check, text=True, capture_output=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Codex MCP configuration for Basecamp"
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Use legacy mcp_server_cli.py instead of FastMCP server",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without modifying Codex configuration",
    )
    args = parser.parse_args()

    print("Generating Codex MCP configuration for Basecamp")
    print("=" * 60)

    project_root = get_project_root()
    python_path = get_python_path(project_root)
    server_name, server_script, server_label = get_server_details(
        project_root, args.legacy
    )
    other_server_name = "basecamp" if args.legacy else "basecamp-legacy"

    print(f"Project root: {project_root}")
    print(f"Selected server: {server_label}")
    print(f"Codex MCP name: {server_name}")

    if shutil.which("codex") is None:
        print("ERROR: `codex` CLI was not found in PATH.")
        print("Install Codex CLI first, then re-run this script.")
        return 1

    if not python_path.exists():
        print(f"ERROR: Python executable not found at {python_path}")
        print("Run `python setup.py` (or uv setup) to create the virtual environment.")
        return 1

    if not server_script.exists():
        print(f"ERROR: MCP server script not found at {server_script}")
        return 1

    env_vars = load_env_vars(project_root)
    add_command = build_codex_add_command(
        server_name, python_path, server_script, env_vars
    )
    remove_same = ["codex", "mcp", "remove", server_name]
    remove_other = ["codex", "mcp", "remove", other_server_name]

    if args.dry_run:
        print("\nDry run mode: no changes will be made.")
        print("Would run:")
        print(f"  {' '.join(remove_same)}")
        print(f"  {' '.join(add_command)}")
        print(f"  {' '.join(remove_other)}")
        return 0

    print("\nApplying Codex MCP configuration...")

    # Remove existing server entry first to keep reruns idempotent.
    run_command(remove_same, check=False)

    try:
        add_result = run_command(add_command, check=True)
        if add_result.stdout:
            print(add_result.stdout.strip())
    except subprocess.CalledProcessError as exc:
        print("ERROR: Failed to add MCP server to Codex.")
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip())
        return exc.returncode

    # Remove counterpart entry to avoid duplicate "basecamp" + "basecamp-legacy".
    run_command(remove_other, check=False)

    print("\nCodex configuration updated successfully.")
    print("\nNext steps:")
    print("1. Verify server registration: codex mcp get " + server_name)
    print("2. List all MCP servers: codex mcp list")
    print("3. Start a new Codex session in this repo and call Basecamp tools")

    return 0


if __name__ == "__main__":
    sys.exit(main())
