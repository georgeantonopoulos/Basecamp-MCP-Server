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
   BASECAMP_CLIENT_ID=your_client_id
   BASECAMP_CLIENT_SECRET=your_client_secret
   BASECAMP_REDIRECT_URI=http://localhost:8000/auth/callback
   USER_AGENT="Your App Name (your@email.com)"
   BASECAMP_ACCOUNT_ID=your_account_id
   FLASK_SECRET_KEY=random_secret_key
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

## Token Management

- Tokens are stored securely in `oauth_tokens.json`
- Tokens refresh automatically when they expire
- View token info at http://localhost:8000/token/info
- Clear tokens at http://localhost:8000/logout

## Security Notes

- File-based token storage is suitable for development
- Use a database or secure key management in production
- Always use HTTPS in production environments

## License

MIT License - see LICENSE file for details. 

## Recent Changes

### March 9, 2024 - Improved MCP Server Functionality

- Added standardized error and success response handling with new `mcp_response` helper function
- Fixed API endpoint issues for Basecamp Campfire (chat) functionality:
  - Updated the URL format for retrieving campfires from `projects/{project_id}/campfire.json` to `buckets/{project_id}/chats.json`
  - Added support for retrieving campfire chat lines
- Enhanced search capabilities to include campfire lines content
- Improved error handling and response formatting across all action handlers
- Fixed CORS support by adding the Flask-CORS package

These changes ensure more reliable and consistent responses from the MCP server, particularly for Campfire chat functionality. 

### March 9, 2024 - Added Local Testing

Added comprehensive test suite for reliable local deployment:
- Unit tests for all MCP endpoints
- Authentication guard testing
- Easy verification with `pytest -q`

## TODO: Composio Integration

**Note: The following Composio integration is planned for future implementation but not currently functional.**

### TODO: March 9, 2024 - Added Composio Integration

TODO: Add support for [Composio](https://composio.dev/) integration, allowing the Basecamp MCP server to be used with Composio for AI-powered workflows. This integration follows the Model Context Protocol (MCP) standards and includes:

- TODO: New endpoints for Composio compatibility:
  - `/composio/schema` - Returns the schema of available tools in Composio-compatible format
  - `/composio/tool` - Handles Composio tool calls with standardized parameters
  - `/composio/check_auth` - Checks authentication status for Composio requests

- TODO: Standardized tool naming and parameter formats to work with Composio's MCP specifications
- TODO: A standalone example client for testing and demonstrating the integration

### TODO: Using with Composio

### TODO: Prerequisites

1. TODO: Create a Composio account at [https://app.composio.dev](https://app.composio.dev)
2. TODO: Obtain a Composio API key from your Composio dashboard
3. TODO: Add your API key to your `.env` file:
   ```
   COMPOSIO_API_KEY=your_composio_api_key
   ```

### TODO: Setting Up Composio Integration

1. TODO: Make sure you have authenticated with Basecamp using the OAuth app (http://localhost:8000/)
2. TODO: Run the MCP server with the Composio integration enabled:
   ```
   python mcp_server.py
   ```

3. TODO: In your Composio dashboard, add a new custom integration:
   - Integration URL: `http://localhost:5001/composio/schema`
   - Authentication: OAuth (managed by our implementation)

4. TODO: You can now use Composio to connect to your Basecamp account through the MCP server:
   - Composio will discover available tools via the schema endpoint
   - Tool executions will be handled by the `/composio/tool` endpoint
   - Authentication status is checked via the `/composio/check_auth` endpoint

### TODO: Example Composio Client

TODO: We provide a simple client example in `composio_client_example.py` that demonstrates how to:

1. Check authentication status
2. Retrieve the tool schema
3. Execute various Basecamp operations through the Composio integration

TODO: Run the example with:
```
python composio_client_example.py
```

### TODO: Testing the Integration

TODO: To test the integration without connecting to Composio:

1. Run the MCP server:
   ```
   python mcp_server.py
   ```

2. Use curl to test the endpoints directly:
   ```bash
   # Check authentication status
   curl http://localhost:5001/composio/check_auth

   # Get the schema
   curl http://localhost:5001/composio/schema

   # Execute a tool (get projects)
   curl -X POST http://localhost:5001/composio/tool \
     -H "Content-Type: application/json" \
     -d '{"tool": "GET_PROJECTS", "params": {}}'
   ```

TODO: For more detailed documentation on Composio integration, refer to the [official Composio documentation](https://docs.composio.dev). 

## Quick Setup for Cursor

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

2. **Create your `.env` file:**
   ```
   BASECAMP_CLIENT_ID=your_client_id
   BASECAMP_CLIENT_SECRET=your_client_secret
   BASECAMP_REDIRECT_URI=http://localhost:8000/auth/callback
   USER_AGENT="Your App Name (your@email.com)"
   BASECAMP_ACCOUNT_ID=your_account_id
   FLASK_SECRET_KEY=random_secret_key
   ```

3. **Authenticate with Basecamp:**
   ```bash
   python oauth_app.py
   ```
   Then visit http://localhost:8000 and complete the OAuth flow.

4. **Generate and install Cursor configuration:**
   ```bash
   python generate_cursor_config.py
   ```
   
   This script will:
   - Generate the correct MCP configuration with full paths
   - Automatically detect your virtual environment
   - Update your Cursor configuration file
   - Provide next steps

5. **Test the CLI server:**
   ```bash
   python -m pytest tests/test_cli_server.py -v
   ```

6. **Restart Cursor completely** (quit and reopen, not just reload)

7. **Verify in Cursor:**
   - Go to Cursor Settings → MCP
   - You should see "basecamp" with a **green checkmark**
   - It should show available tools like "get_projects", "search_basecamp", etc.

### Critical Configuration Requirements

Based on the [Cursor community forum](https://forum.cursor.com/t/mcp-servers-no-tools-found/49094), the following are essential for MCP servers to work properly:

1. **Full executable paths** (not just "python")
2. **Proper environment variables** (PYTHONPATH, VIRTUAL_ENV)
3. **Correct working directory** (cwd)
4. **MCP protocol compliance** (handling 'initialized' notifications)

### Manual Configuration (if needed)

If the automatic configuration doesn't work, manually edit your Cursor MCP configuration:

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

### Troubleshooting

- **Yellow indicator (not green):** Check that the full Python path is correct and virtual environment exists
- **"No tools available":** Make sure you completed OAuth authentication first (`python oauth_app.py`)
- **"Tool not found" errors:** Restart Cursor completely and check `mcp_cli_server.log` for errors
- **Server not starting:** Verify all paths in the configuration are absolute and correct
- **Can't find mcp.json:** Run `python generate_cursor_config.py` to create it automatically

### Testing Without Cursor

You can test the MCP server directly:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | python mcp_server_cli.py
```

### What Fixed the Yellow/Green Issue

The key fixes that resolve the "yellow indicator" and "tool not found" issues mentioned in the [Cursor forums](https://forum.cursor.com/t/mcp-tools-enabled-in-settings-but-cursor-not-detecting-tools/96663):

1. **Full Python executable path** instead of just "python"
2. **Environment variables** for PYTHONPATH and VIRTUAL_ENV
3. **Proper MCP protocol handling** including the 'initialized' notification
4. **Absolute paths** for all configuration values 