# Basecamp MCP Integration

This project provides a MCP (Model Context Protocol) integration for Basecamp 3, allowing Cursor to interact with Basecamp directly through the MCP protocol.

## Quick Setup for Cursor

### Prerequisites

- Python 3.7+
- A Basecamp 3 account
- A Basecamp OAuth application (create one at https://launchpad.37signals.com/integrations)

### Step-by-Step Instructions

1. **Clone and setup the project:**
   ```bash
   git clone <repository-url>
   cd basecamp-mcp
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

2. **Create your `.env` file with your Basecamp OAuth credentials:**
   ```
   BASECAMP_CLIENT_ID=your_client_id_here
   BASECAMP_CLIENT_SECRET=your_client_secret_here
   BASECAMP_REDIRECT_URI=http://localhost:8000/auth/callback
   BASECAMP_ACCOUNT_ID=your_account_id_here
   USER_AGENT="Your App Name (your@email.com)"
   FLASK_SECRET_KEY=any_random_string_here
   MCP_API_KEY=any_random_string_here
   ```

3. **Authenticate with Basecamp:**
   ```bash
   python oauth_app.py
   ```
   Visit http://localhost:8000 and complete the OAuth flow.

4. **Generate and install Cursor configuration:**
   ```bash
   python generate_cursor_config.py
   ```

   This script will:
   - Generate the correct MCP configuration with full paths
   - Automatically detect your virtual environment
   - Include the BASECAMP_ACCOUNT_ID environment variable
   - Update your Cursor configuration file automatically

5. **Restart Cursor completely** (quit and reopen, not just reload)

6. **Verify in Cursor:**
   - Go to Cursor Settings → MCP
   - You should see "basecamp" with a **green checkmark**
   - Available tools: "get_projects", "search_basecamp", "get_project", etc.

### Test Your Setup

```bash
# Quick test the MCP server
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python mcp_server_cli.py

# Run automated tests
python -m pytest tests/ -v
```

## Available MCP Tools

Once configured, you can use these tools in Cursor:

- `get_projects` - Get all Basecamp projects
- `get_project` - Get details for a specific project
- `get_todolists` - Get todo lists for a project
- `get_todos` - Get todos from a todo list
- `search_basecamp` - Search across projects, todos, and messages
- `get_comments` - Get comments for a Basecamp item

### Example Cursor Usage

Ask Cursor things like:
- "Show me all my Basecamp projects"
- "What todos are in project X?"
- "Search for messages containing 'deadline'"
- "Get details for the Technology project"

## Architecture

The project consists of:

1. **OAuth App** (`oauth_app.py`) - Handles OAuth 2.0 flow with Basecamp
2. **MCP Server** (`mcp_server_cli.py`) - Implements MCP protocol for Cursor
3. **Token Storage** (`token_storage.py`) - Securely stores OAuth tokens
4. **Basecamp Client** (`basecamp_client.py`) - Basecamp API client library
5. **Search Utilities** (`search_utils.py`) - Search across Basecamp resources

## Troubleshooting

### Common Issues

- **Yellow indicator (not green):** Check that paths in Cursor config are correct
- **"No tools available":** Make sure you completed OAuth authentication first
- **"Tool not found" errors:** Restart Cursor completely and check `mcp_cli_server.log`
- **Missing BASECAMP_ACCOUNT_ID:** The config generator automatically includes this from your `.env` file

### Configuration Issues

If automatic configuration doesn't work, manually edit your Cursor MCP configuration:

**On macOS/Linux:** `~/.cursor/mcp.json`
**On Windows:** `%APPDATA%\Cursor\mcp.json`

```json
{
    "mcpServers": {
        "basecamp": {
            "command": "/full/path/to/your/project/venv/bin/python",
            "args": ["/full/path/to/your/project/mcp_server_cli.py"],
            "cwd": "/full/path/to/your/project",
            "env": {
                "PYTHONPATH": "/full/path/to/your/project",
                "VIRTUAL_ENV": "/full/path/to/your/project/venv",
                "BASECAMP_ACCOUNT_ID": "your_account_id"
            }
        }
    }
}
```

### Key Requirements

Based on [Cursor community forums](https://forum.cursor.com/t/mcp-servers-no-tools-found/49094), the following are essential:

1. **Full executable paths** (not just "python")
2. **Proper environment variables** (PYTHONPATH, VIRTUAL_ENV, BASECAMP_ACCOUNT_ID)
3. **Correct working directory** (cwd)
4. **MCP protocol compliance** (our server handles this correctly)

## Finding Your Account ID

If you don't know your Basecamp account ID:
1. Log into Basecamp in your browser
2. Look at the URL - it will be like `https://3.basecamp.com/4389629/projects`
3. The number (4389629 in this example) is your account ID

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- The OAuth tokens are stored locally in `oauth_tokens.json`
- This setup is designed for local development use

## License

This project is licensed under the MIT License.
