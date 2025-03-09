# Basecamp MCP Integration

This project provides a MCP (Magic Copy Paste) integration for Basecamp 3, allowing Cursor to interact with Basecamp directly through the MCP protocol.

## Architecture

The project consists of the following components:

1. **OAuth App** (`oauth_app.py`) - A Flask application that handles the OAuth 2.0 flow with Basecamp.
2. **Token Storage** (`token_storage.py`) - A module for securely storing OAuth tokens.
3. **MCP Server** (`mcp_server.py`) - A Flask server that implements the MCP protocol for Basecamp.
4. **Basecamp Client** (`basecamp_client.py`) - A client library for interacting with the Basecamp API.
5. **Basecamp OAuth** (`basecamp_oauth.py`) - A utility for handling OAuth authentication with Basecamp.
6. **Search Utilities** (`search_utils.py`) - Utilities for searching Basecamp resources.

## Setup

### Prerequisites

- Python 3.7+
- A Basecamp 3 account
- A Basecamp OAuth application (create one at https://launchpad.37signals.com/integrations)

### Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   cd basecamp-mcp
   ```

2. Create and activate a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Create a `.env` file with the following variables:
   ```
   BASECAMP_CLIENT_ID=your_client_id
   BASECAMP_CLIENT_SECRET=your_client_secret
   BASECAMP_REDIRECT_URI=http://localhost:8000/auth/callback
   USER_AGENT="Your App Name (your@email.com)"
   BASECAMP_ACCOUNT_ID=your_account_id
   FLASK_SECRET_KEY=random_secret_key
   MCP_API_KEY=your_api_key
   ```

## Usage

### Starting the Servers

1. Start the OAuth app:
   ```
   python oauth_app.py
   ```

2. Start the MCP server:
   ```
   python mcp_server.py
   ```

### OAuth Authentication

1. Visit http://localhost:8000/ in your browser
2. Click "Log in with Basecamp"
3. Follow the OAuth flow to authorize the application
4. The token will be stored securely in the token storage

### Using with Cursor

1. In Cursor, add the MCP server URL: http://localhost:5001
2. Interact with Basecamp through the Cursor interface
3. The MCP server will use the stored OAuth token to authenticate with Basecamp

### Authentication Flow

When using the MCP server with Cursor, the authentication flow is as follows:

1. Cursor makes a request to the MCP server
2. The MCP server checks if OAuth authentication has been completed
3. If not, it returns an error with instructions to authenticate
4. You authenticate using the OAuth app at http://localhost:8000/
5. After authentication, Cursor can make requests to the MCP server

### MCP Server API

The MCP server has two main methods for interacting with Basecamp:

**Preferred Method: Connection-based Approach**

This approach is recommended as it provides better error handling and state management:

1. Initiate a connection:
   ```
   POST /initiate_connection
   {
     "auth_mode": "oauth"
   }
   ```

2. Use the returned connection ID to make tool calls:
   ```
   POST /tool/<connection_id>
   {
     "action": "get_projects"
   }
   ```

If OAuth authentication hasn't been completed, the MCP server will return an error with instructions to authenticate.

**Alternative Method: Direct Action**

For simple requests, you can use the action endpoint:

```
POST /mcp/action
{
  "action": "get_projects"
}
```

This method also checks for OAuth authentication and returns appropriate error messages if needed.

## Token Management

- Tokens are stored in `oauth_tokens.json` 
- The token will be refreshed automatically when it expires
- You can view token info at http://localhost:8000/token/info
- You can logout and clear the token at http://localhost:8000/logout

## Troubleshooting

- **Token Issues**: If you encounter authentication errors, try logging out and logging in again through the OAuth app
- **MCP Connection Issues**: Make sure both the OAuth app and MCP server are running
- **API Errors**: Check the logs in `oauth_app.log` and `mcp_server.log` for detailed error messages

## Security Considerations

- This implementation uses file-based token storage, which is suitable for development but not for production
- In a production environment, use a database or secure key management service for token storage
- Always use HTTPS in production and implement proper authentication for the API endpoints

## License

This project is licensed under the MIT License - see the LICENSE file for details. 