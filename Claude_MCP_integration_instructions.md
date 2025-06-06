# Integrating Your Basecamp MCP Server with Anthropic Claude

This guide explains how to connect your custom Basecamp MCP (Model Context Protocol) server to Anthropic's Claude AI, enabling Claude to use your Basecamp tools. This process leverages Claude's "Custom Integrations" feature for "Remote MCP servers."

**Prerequisites:**
*   A paid Anthropic Claude plan (Max, Team, or Enterprise) is required to use custom integrations with remote MCP servers.
*   Your Basecamp MCP server code (including `mcp_server.py`, `composio_integration.py`, `oauth_app.py`, etc.).
*   Basecamp application credentials (Client ID, Client Secret).

---

## Phase 1: Server Preparation & Pre-authentication

1.  **Environment Setup:**
    *   Ensure you have Python (3.10+ recommended).
    *   Open a terminal in your project's root directory.
    *   Create and activate a Python virtual environment:
        ```bash
        python -m venv venv
        source venv/bin/activate  # On Windows: venv\Scripts\activate
        ```
    *   Install necessary Python packages:
        ```bash
        pip install -r requirements.txt requests python-dotenv flask-cors
        ```

2.  **Configuration (`.env` file):**
    *   Ensure your `.env` file in the project root is correctly populated with your Basecamp App credentials and server settings. Create one if it doesn't exist (e.g., from a `.env.example`):
        ```dotenv
        BASECAMP_ACCOUNT_ID=your_basecamp_account_id
        BASECAMP_CLIENT_ID=your_basecamp_app_client_id
        BASECAMP_CLIENT_SECRET=your_basecamp_app_client_secret
        BASECAMP_REDIRECT_URI=http://localhost:8000/callback # Used by oauth_app.py
        USER_AGENT=YourAppName/1.0 (yourcontact@example.com) # Or any valid User-Agent
        MCP_PORT=5001 # Default port for your MCP server
        FLASK_DEBUG=False # Recommended for anything beyond local testing
        ```

3.  **Pre-authenticate with Basecamp (Crucial):**
    *   Before exposing your MCP server publicly for Claude, you *must* obtain valid Basecamp OAuth tokens and store them locally for the server to use.
    *   Run the standalone OAuth helper application provided in your repository:
        ```bash
        (venv) $ python oauth_app.py
        ```
    *   This will typically start a local web server on `http://localhost:8000`.
    *   Open `http://localhost:8000` in your web browser.
    *   Follow the on-screen prompts to authenticate with your Basecamp account and authorize your application.
    *   Upon successful authentication, `oauth_app.py` will create/update a file named `oauth_tokens.json` in your project root. This file contains the `access_token` and `refresh_token` that `mcp_server.py` will use.
    *   **Why this is important:** This step ensures your MCP server is already authenticated with Basecamp. When Claude connects, the server can directly use these stored tokens (and refresh them as needed using `refresh_oauth_token`) without requiring Claude to handle a redirect to a `localhost` OAuth URL, which wouldn't work for a remote service.

4.  **Run Your MCP Server Locally (for initial verification):**
    *   Once `oauth_tokens.json` exists and is populated, start your main MCP server:
        ```bash
        (venv) $ python mcp_server.py
        ```
    *   The server should now be running, typically at `http://localhost:5001`. You can test basic health: `curl http://localhost:5001/health`.

---

## Phase 2: Making Your MCP Server Publicly Accessible

Claude's servers need to be able to reach your MCP server over the internet.

1.  **Using ngrok (Recommended for Development/Testing):**
    *   Download and install ngrok from [ngrok.com](https://ngrok.com/).
    *   Authenticate ngrok if it's your first time (see ngrok's documentation).
    *   With your MCP server running locally (from Phase 1, Step 4), open a new terminal window and run:
        ```bash
        ngrok http 5001
        ```
        (Replace `5001` if your `MCP_PORT` is different).
    *   ngrok will display a public HTTPS URL (e.g., `https://<unique-string>.ngrok-free.app`). **Copy this HTTPS URL.** This will be your `YOUR_PUBLIC_MCP_SERVER_URL` used when configuring Claude.

2.  **Production Deployment (Advanced):**
    *   For a permanent or production setup, you would deploy `mcp_server.py` as a WSGI application (e.g., using Gunicorn behind an Nginx reverse proxy) to a cloud provider (AWS, Google Cloud, Azure, Heroku, etc.).
    *   Ensure your production deployment is configured with HTTPS.

---

## Phase 3: Adding the MCP Server to Claude.ai

**Note:** This requires a paid Claude plan (Claude Max, Team, or Enterprise).

1.  **Navigate to Claude.ai Settings:**
    *   Log in to your Claude.ai account.
    *   For **Claude Max users:** Go to `Settings` > `Profile`.
    *   For **Claude Team or Enterprise users:** Go to `Settings` > `Integrations` (for Teams) or `Settings` > `Data management` (for Enterprise). *Note: Only Primary Owners or Owners can add new integrations on Team/Enterprise plans.*

2.  **Add Custom Integration:**
    *   Look for a section titled "Integrations" or similar.
    *   Click on an option like "Add more," "Add custom integration," or "Connect new integration."
    *   You will be prompted to enter your "integration's remote MCP server URL" (or similar wording).

3.  **Provide Server URL and Configure:**
    *   Enter the public HTTPS URL of your MCP server obtained in Phase 2 (e.g., your ngrok URL like `https://<unique-string>.ngrok-free.app`).
    *   Claude will attempt to connect to this URL to:
        *   Discover available tools: It typically looks for a schema endpoint. Your server provides this at `/composio/schema` (e.g., `https://<your_url>/composio/schema`).
        *   Check authentication status: It uses `/composio/check_auth`. Because you pre-authenticated in Phase 1, this endpoint should return `{"authenticated": True}`, and Claude should not need to initiate a new OAuth flow with Basecamp.
    *   Follow any on-screen prompts in the Claude interface to complete the configuration and save the integration.

---

## Phase 4: Using the Integration in Claude

1.  **Enable Tools in Chat:**
    *   Once the integration is successfully added, you can enable it and its specific tools (e.g., `GET_PROJECTS`, `CREATE_COMMENT`, as defined in your `composio_integration.py`) within a Claude chat.
    *   Look for a "Search and tools" menu (often a briefcase icon or similar) in the chat interface. From here, you can toggle your Basecamp integration and select/deselect individual tools for the current conversation.

2.  **Interact with Claude:**
    *   You can now ask Claude to perform actions using your Basecamp tools. For example:
        *   "Claude, what are my current projects in Basecamp?"
        *   "Can you get the to-do lists for the 'Marketing Campaign' project?"
        *   "Create a new to-do item in the 'Website Launch' list with the content 'Finalize homepage design'."
    *   Claude will communicate with your MCP server (via the public URL) to execute these actions.

---

## Important Considerations & Potential Adjustments

1.  **Schema Endpoint (`/composio/schema`):**
    *   Your `mcp_server.py` uses `composio_integration.py` which exposes tool schemas at the `/composio/schema` path. Claude's remote MCP integration feature should discover this.
    *   The schema format in `composio_integration.py` uses a `"parameters"` key for defining tool inputs. Standard Claude tool use often refers to an `"input_schema"` key. While MCP is an open standard, if Claude has trouble understanding your tool parameters, you might need to modify `composio_integration.py` to rename `"parameters"` to `"input_schema"` within the `get_schema()` function for each tool.

2.  **Tool Execution Endpoint (`/composio/tool`):**
    *   Tool execution requests from Claude will be directed to the `/composio/tool` endpoint on your server.

3.  **Security:**
    *   **Public Endpoint:** Remember that your ngrok URL (or production URL) makes your MCP server publicly accessible. While `oauth_tokens.json` is not directly exposed, the server itself is. For production, implement robust security measures:
        *   Ensure HTTPS is enforced.
        *   Consider adding an API key or other authentication layer directly to your MCP server endpoints (`/composio/schema`, `/composio/tool`) to prevent unauthorized access. The `composio_integration.py` file has a placeholder for checking an `X-Composio-API-Key` header; you could adapt this.
    *   **Permissions:** Be mindful of the permissions granted to your Basecamp application. The tools will operate with these permissions.
    *   **Anthropic's Guidance:** Always review Anthropic's security and privacy considerations for custom integrations.

4.  **Logging and Debugging:**
    *   Your `mcp_server.py` includes logging. Monitor these logs (e.g., `improved_mcp_server.log` and console output) on your server when setting up and testing the integration to diagnose any issues.
    *   If using ngrok, its web interface (`http://localhost:4040` by default) provides a request inspector which is very helpful for debugging.

5.  **Firewall/Network:**
    *   If deploying to a server with a firewall, ensure the port your MCP server is running on (e.g., 5001) allows inbound HTTPS traffic.

By following these steps, you should be able to successfully integrate your Basecamp MCP server with Anthropic Claude, empowering Claude with your custom Basecamp functionalities.
