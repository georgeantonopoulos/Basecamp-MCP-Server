#!/usr/bin/env python3
"""
Generate the correct Cursor MCP configuration for this Basecamp MCP server.
Supports both the new FastMCP server (default) and legacy server during migration.
"""

import json
import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv

def get_project_root():
    """Get the absolute path to the project root."""
    return str(Path(__file__).parent.absolute())

def get_python_path():
    """Get the path to the Python executable in the virtual environment."""
    project_root = get_project_root()
    venv_python = os.path.join(project_root, "venv", "bin", "python")

    if os.path.exists(venv_python):
        return venv_python

    # Fallback to system Python
    return sys.executable

def generate_config(use_legacy=False):
    """Generate the MCP configuration for Cursor.
    
    Args:
        use_legacy: If True, use the legacy mcp_server_cli.py. If False, use new FastMCP server.
    """
    project_root = get_project_root()
    python_path = get_python_path()
    
    if use_legacy:
        # Use legacy server
        script_path = os.path.join(project_root, "mcp_server_cli.py")
        server_name = "basecamp-legacy"
        print("🔄 Using LEGACY server (mcp_server_cli.py)")
    else:
        # Use new FastMCP server (default)
        script_path = os.path.join(project_root, "basecamp_fastmcp.py")
        server_name = "basecamp"
        print("✨ Using NEW FastMCP server (basecamp_fastmcp.py) - RECOMMENDED")

    # Load .env file from project root to get BASECAMP_ACCOUNT_ID
    dotenv_path = os.path.join(project_root, ".env")
    load_dotenv(dotenv_path)
    basecamp_account_id = os.getenv("BASECAMP_ACCOUNT_ID")

    env_vars = {
        "PYTHONPATH": project_root,
        "VIRTUAL_ENV": os.path.join(project_root, "venv")
    }
    if basecamp_account_id:
        env_vars["BASECAMP_ACCOUNT_ID"] = basecamp_account_id
    else:
        print("⚠️ WARNING: BASECAMP_ACCOUNT_ID not found in .env file. MCP server might not work correctly.")
        print(f"   Attempted to load .env from: {dotenv_path}")

    config = {
        "mcpServers": {
            server_name: {
                "command": python_path,
                "args": [script_path],
                "cwd": project_root,
                "env": env_vars
            }
        }
    }

    return config, server_name

def get_cursor_config_path():
    """Get the path to the Cursor MCP configuration file."""
    home = Path.home()

    if sys.platform == "darwin":  # macOS
        return home / ".cursor" / "mcp.json"
    elif sys.platform == "win32":  # Windows
        return Path(os.environ.get("APPDATA", home)) / "Cursor" / "mcp.json"
    else:  # Linux
        return home / ".cursor" / "mcp.json"

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Generate Cursor MCP configuration for Basecamp")
    parser.add_argument("--legacy", action="store_true", 
                       help="Use legacy mcp_server_cli.py instead of new FastMCP server")
    args = parser.parse_args()

    config, server_name = generate_config(use_legacy=args.legacy)
    config_path = get_cursor_config_path()

    print("🔧 Generated Cursor MCP Configuration:")
    print(json.dumps(config, indent=2))
    print()

    print(f"📁 Configuration should be saved to: {config_path}")
    print()

    # Check if the file exists and offer to update it
    if config_path.exists():
        print("⚠️  Configuration file already exists.")
        response = input("Do you want to update it? (y/N): ").lower().strip()

        if response in ['y', 'yes']:
            # Read existing config
            try:
                with open(config_path, 'r') as f:
                    existing_config = json.load(f)

                # Update the basecamp server configuration
                if "mcpServers" not in existing_config:
                    existing_config["mcpServers"] = {}

                existing_config["mcpServers"][server_name] = config["mcpServers"][server_name]

                # Clean up old server entries if switching
                if not args.legacy and "basecamp-legacy" in existing_config["mcpServers"]:
                    print("🧹 Removing legacy server configuration...")
                    del existing_config["mcpServers"]["basecamp-legacy"]
                elif args.legacy and "basecamp" in existing_config["mcpServers"]:
                    print("🧹 Removing new FastMCP server configuration...")
                    del existing_config["mcpServers"]["basecamp"]

                # Write back the updated config
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, 'w') as f:
                    json.dump(existing_config, f, indent=2)

                print("✅ Configuration updated successfully!")

            except Exception as e:
                print(f"❌ Error updating configuration: {e}")

        else:
            print("Configuration not updated.")
    else:
        response = input("Do you want to create the configuration file? (y/N): ").lower().strip()

        if response in ['y', 'yes']:
            try:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)

                print("✅ Configuration file created successfully!")

            except Exception as e:
                print(f"❌ Error creating configuration file: {e}")
        else:
            print("Configuration file not created.")

    print()
    if args.legacy:
        print("📋 Next steps (Legacy Server):")
        print("1. Make sure you've authenticated with Basecamp: python oauth_app.py")
        print("2. Restart Cursor completely (quit and reopen)")
        print("3. Check Cursor Settings → MCP for a green checkmark next to 'basecamp-legacy'")
        print()
        print("💡 TIP: Try the new FastMCP server by running without --legacy flag!")
    else:
        print("📋 Next steps (FastMCP Server):")
        print("1. Make sure you've authenticated with Basecamp: python oauth_app.py")
        print("2. Restart Cursor completely (quit and reopen)")
        print("3. Check Cursor Settings → MCP for a green checkmark next to 'basecamp'")
        print()
        print("🚀 You're using the new FastMCP server - enjoy the improved performance!")
        print("🔄 If you encounter issues, you can switch back with: python generate_cursor_config.py --legacy")

if __name__ == "__main__":
    main()
