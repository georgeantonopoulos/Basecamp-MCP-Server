#!/usr/bin/env python3
"""
Generate Claude Desktop configuration for Basecamp MCP Integration.
Based on official MCP quickstart guide: https://modelcontextprotocol.io/quickstart/server
"""

import os
import sys
import json
import platform
from pathlib import Path
from dotenv import load_dotenv

def get_project_root():
    """Get the absolute path to the project root."""
    return os.path.abspath(os.path.dirname(__file__))

def get_python_path():
    """Get the Python executable path from virtual environment."""
    project_root = get_project_root()
    
    if platform.system() == "Windows":
        python_path = os.path.join(project_root, "venv", "Scripts", "python.exe")
    else:
        python_path = os.path.join(project_root, "venv", "bin", "python")
    
    # Convert to absolute path
    return os.path.abspath(python_path)

def get_claude_desktop_config_path():
    """Get the Claude Desktop configuration file path."""
    if platform.system() == "Windows":
        return os.path.expanduser("~/AppData/Roaming/Claude/claude_desktop_config.json")
    elif platform.system() == "Darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    else:  # Linux
        return os.path.expanduser("~/.config/claude-desktop/claude_desktop_config.json")

def generate_config():
    """Generate the Claude Desktop configuration for Basecamp MCP server."""
    project_root = get_project_root()
    python_path = get_python_path()
    script_path = os.path.join(project_root, "basecamp_fastmcp.py")
    
    # Load .env file to get BASECAMP_ACCOUNT_ID
    dotenv_path = os.path.join(project_root, ".env")
    load_dotenv(dotenv_path)
    basecamp_account_id = os.getenv("BASECAMP_ACCOUNT_ID")
    
    if not basecamp_account_id:
        print("⚠️  Warning: BASECAMP_ACCOUNT_ID not found in .env file")
        print("   Add BASECAMP_ACCOUNT_ID to your .env file for proper configuration")
        basecamp_account_id = "YOUR_ACCOUNT_ID_HERE"
    
    # Verify Python executable exists
    if not os.path.exists(python_path):
        print(f"❌ Python executable not found at {python_path}")
        print("   Run 'python setup.py' first to create the virtual environment")
        return False
    
    # Verify FastMCP server exists
    if not os.path.exists(script_path):
        print(f"❌ FastMCP server not found at {script_path}")
        return False
    
    # Create configuration
    config = {
        "mcpServers": {
            "basecamp": {
                "command": python_path,
                "args": [script_path],
                "env": {
                    "PYTHONPATH": project_root,
                    "VIRTUAL_ENV": os.path.join(project_root, "venv"),
                    "BASECAMP_ACCOUNT_ID": basecamp_account_id
                }
            }
        }
    }
    
    config_path = get_claude_desktop_config_path()
    config_dir = os.path.dirname(config_path)
    
    # Create config directory if it doesn't exist
    os.makedirs(config_dir, exist_ok=True)
    
    # Load existing config if it exists
    existing_config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                existing_config = json.load(f)
        except json.JSONDecodeError:
            print(f"⚠️  Warning: Existing config at {config_path} has invalid JSON")
            existing_config = {}
    
    # Merge with existing mcpServers
    if "mcpServers" not in existing_config:
        existing_config["mcpServers"] = {}
    
    # Add or update Basecamp server
    existing_config["mcpServers"]["basecamp"] = config["mcpServers"]["basecamp"]
    
    # Write configuration
    try:
        with open(config_path, 'w') as f:
            json.dump(existing_config, f, indent=2)
        
        print("✅ Claude Desktop configuration updated successfully!")
        print(f"📍 Config file: {config_path}")
        print("\n📋 Configuration details:")
        print(f"   • Server name: basecamp")
        print(f"   • Python path: {python_path}")
        print(f"   • Server script: {script_path}")
        print(f"   • Account ID: {basecamp_account_id}")
        print("\n🔄 Next steps:")
        print("   1. Restart Claude Desktop completely")
        print("   2. Look for the MCP tools icon in Claude Desktop")
        print("   3. Enable Basecamp tools in your conversation")
        print("\n💡 Tip: Check ~/Library/Logs/Claude/mcp*.log for troubleshooting")
        
        return True
        
    except Exception as e:
        print(f"❌ Error writing configuration: {str(e)}")
        return False

def main():
    """Main function."""
    print("🚀 Generating Claude Desktop Configuration for Basecamp MCP")
    print("=" * 60)
    
    if not generate_config():
        sys.exit(1)

if __name__ == "__main__":
    main() 