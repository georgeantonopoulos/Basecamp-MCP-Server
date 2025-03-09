#!/bin/bash

echo "Starting Basecamp MCP integration..."

# Kill any existing processes
echo "Stopping any existing servers..."
pkill -f "python oauth_app.py" 2>/dev/null || true
pkill -f "python mcp_server.py" 2>/dev/null || true
sleep 1

# Check if virtual environment exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Start the OAuth app
echo "Starting OAuth app on port 8000..."
nohup python oauth_app.py > oauth_app.log 2>&1 < /dev/null &
OAUTH_PID=$!
echo "OAuth app started with PID: $OAUTH_PID"

# Wait a bit for OAuth app to start
sleep 2

# Start the MCP server
echo "Starting MCP server on port 5001..."
nohup python mcp_server.py > mcp_server.log 2>&1 < /dev/null &
MCP_PID=$!
echo "MCP server started with PID: $MCP_PID"

echo ""
echo "Basecamp MCP integration is now running:"
echo "- OAuth app: http://localhost:8000"
echo "- MCP server: http://localhost:5001"
echo ""
echo "To stop the servers, run: pkill -f 'python oauth_app.py' && pkill -f 'python mcp_server.py'"
echo ""
echo "To check server logs, run:"
echo "- OAuth app logs: tail -f oauth_app.log"
echo "- MCP server logs: tail -f mcp_server.log"
echo ""
echo "To use with Cursor, configure a new MCP server with URL: http://localhost:5001" 