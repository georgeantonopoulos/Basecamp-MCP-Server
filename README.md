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
   - Visit http://localhost:8000 in your browser
   - Click "Log in with Basecamp" and complete the OAuth flow
   - Keep the OAuth app running in the background

4. **Generate Cursor configuration:**
   ```bash
   python generate_cursor_config.py
   ```
   This will automatically create the Cursor MCP configuration file in the correct location.

5. **Restart Cursor** to load the new MCP configuration.

6. **Test the integration** by using the Basecamp MCP tools in Cursor!

## Available MCP Tools

Once configured, you can use these tools in Cursor:

- **Get Projects**: List all your Basecamp projects
- **Get Project**: Get details for a specific project  
- **Get Todo Lists**: Get todo lists for a project
- **Get Todos**: Get todos from a todo list
- **Search Basecamp**: Search across projects, todos, and messages
- **Get Comments**: Get comments for any Basecamp item
- **Get Campfire Lines**: Get recent messages from project chat rooms

## Troubleshooting

### Authentication Issues
- Make sure the OAuth app is running: `python oauth_app.py`
- Visit http://localhost:8000 and re-authenticate if needed
- Check that your `.env` file has the correct credentials

### Cursor Connection Issues
- Restart Cursor after running `generate_cursor_config.py`
- Check that the generated configuration includes your `BASECAMP_ACCOUNT_ID`
- Make sure your virtual environment is activated when running the OAuth app

### Finding Your Account ID
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