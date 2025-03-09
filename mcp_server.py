#!/usr/bin/env python
import os
import sys
import json
import logging
import traceback
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from threading import Thread
import time
from basecamp_client import BasecampClient
from search_utils import BasecampSearch
import token_storage  # Import the token storage module
import requests  # For token refresh

# Import MCP integration components, using try/except to catch any import errors
try:
    from mcp_integration import (
        get_required_parameters,
        initiate_connection,
        check_active_connection,
        get_projects,
        get_todo_lists,
        get_todos,
        get_comments,
        create_comment,
        update_comment,
        delete_comment,
        search_all
    )
except Exception as e:
    print(f"Error importing MCP integration: {str(e)}")
    traceback.print_exc()
    sys.exit(1)

# Configure logging with more verbose output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('improved_mcp_server.log')
    ]
)
logger = logging.getLogger('mcp_server')

# Load environment variables from .env file
try:
    load_dotenv()
    logger.info("Environment variables loaded")
except Exception as e:
    logger.error(f"Error loading environment variables: {str(e)}")

# Create Flask app
app = Flask(__name__)

# MCP Server configuration
MCP_PORT = int(os.environ.get('MCP_PORT', 5001))
BASECAMP_ACCOUNT_ID = os.environ.get('BASECAMP_ACCOUNT_ID')
USER_AGENT = os.environ.get('USER_AGENT')
CLIENT_ID = os.environ.get('BASECAMP_CLIENT_ID')
CLIENT_SECRET = os.environ.get('BASECAMP_CLIENT_SECRET')
REDIRECT_URI = os.environ.get('BASECAMP_REDIRECT_URI')

# Token endpoints
TOKEN_URL = "https://launchpad.37signals.com/authorization/token"

# Keep track of existing connections
active_connections = {}

def refresh_oauth_token():
    """
    Refresh the OAuth token if it's expired.
    
    Returns:
        str: The new access token if successful, None otherwise
    """
    try:
        # Get current token data
        token_data = token_storage.get_token()
        if not token_data or not token_data.get('refresh_token'):
            logger.error("No refresh token available")
            return None
            
        refresh_token = token_data['refresh_token']
        
        # Prepare the refresh request
        data = {
            'type': 'refresh',
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'refresh_token': refresh_token
        }
        
        headers = {
            'User-Agent': USER_AGENT
        }
        
        logger.info("Refreshing OAuth token")
        response = requests.post(TOKEN_URL, data=data, headers=headers, timeout=10)
        
        if response.status_code == 200:
            new_token_data = response.json()
            logger.info("Token refresh successful")
            
            # Store the new token
            access_token = new_token_data.get('access_token')
            new_refresh_token = new_token_data.get('refresh_token') or refresh_token  # Use old refresh if not provided
            expires_in = new_token_data.get('expires_in')
            
            token_storage.store_token(
                access_token=access_token,
                refresh_token=new_refresh_token,
                expires_in=expires_in,
                account_id=BASECAMP_ACCOUNT_ID
            )
            
            return access_token
        else:
            logger.error(f"Failed to refresh token: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        return None

def get_basecamp_client(auth_mode='oauth'):
    """
    Get a Basecamp client with the appropriate authentication.
    
    Args:
        auth_mode (str): Authentication mode, either 'oauth' or 'pat' (Personal Access Token)
    
    Returns:
        BasecampClient: A configured client
    """
    logger.info(f"Getting Basecamp client with auth_mode: {auth_mode}")
    
    if auth_mode == 'oauth':
        # Get the token from storage
        token_data = token_storage.get_token()
        
        # If no token or token is expired, try to refresh
        if not token_data or not token_data.get('access_token') or token_storage.is_token_expired():
            logger.info("Token missing or expired, attempting to refresh")
            access_token = refresh_oauth_token()
            if not access_token:
                logger.error("No OAuth token available after refresh attempt")
                raise ValueError("No OAuth token available. Please authenticate first.")
        else:
            access_token = token_data['access_token']
            
        account_id = token_data.get('account_id') or BASECAMP_ACCOUNT_ID
        
        if not account_id:
            logger.error("No account ID available")
            raise ValueError("No Basecamp account ID available. Please set BASECAMP_ACCOUNT_ID.")
        
        logger.info(f"Using OAuth token (starts with {access_token[:5]}...) for account {account_id}")
        
        return BasecampClient(
            access_token=access_token,
            account_id=account_id,
            user_agent=USER_AGENT,
            auth_mode='oauth'
        )
    elif auth_mode == 'pat':
        # Use Personal Access Token
        username = os.environ.get('BASECAMP_USERNAME')
        token = os.environ.get('BASECAMP_TOKEN')
        account_id = BASECAMP_ACCOUNT_ID
        
        if not username or not token or not account_id:
            logger.error("Missing credentials for PAT authentication")
            raise ValueError("Missing credentials for PAT authentication")
        
        logger.info(f"Using PAT authentication for user {username} and account {account_id}")
        
        return BasecampClient(
            username=username,
            token=token,
            account_id=account_id,
            user_agent=USER_AGENT,
            auth_mode='pat'
        )
    else:
        logger.error(f"Invalid auth mode: {auth_mode}")
        raise ValueError(f"Invalid auth mode: {auth_mode}")

# Basic health check endpoint for testing server responsiveness
@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint that returns a static response."""
    logger.debug("Health check endpoint called")
    return jsonify({"status": "ok", "message": "MCP server is running"}), 200

# Enable CORS for all routes
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    logger.debug(f"CORS headers added to response: {response}")
    return response

# Add OPTIONS method handler for CORS preflight requests
@app.route('/', defaults={'path': ''}, methods=['OPTIONS'])
@app.route('/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    """Handle OPTIONS preflight requests for CORS."""
    logger.debug(f"OPTIONS request for path: {path}")
    return '', 200

# MCP Info endpoint
@app.route('/mcp/info', methods=['GET'])
def mcp_info():
    """Return information about this MCP server."""
    logger.info("MCP info endpoint called")
    try:
        # Keep this operation lightweight - no external API calls here
        return jsonify({
            "name": "Basecamp",
            "version": "1.0.0",
            "description": "Basecamp 3 API integration for Cursor",
            "author": "Cursor",
            "actions": [
                {
                    "name": "get_required_parameters",
                    "description": "Get required parameters for connecting to Basecamp"
                },
                {
                    "name": "initiate_connection",
                    "description": "Connect to Basecamp using credentials"
                },
                {
                    "name": "check_active_connection",
                    "description": "Check if the connection to Basecamp is active"
                },
                {
                    "name": "get_projects",
                    "description": "Get all projects with optional filtering"
                },
                {
                    "name": "get_todo_lists",
                    "description": "Get all to-do lists for a project"
                },
                {
                    "name": "get_todos",
                    "description": "Get all to-dos with various filters"
                },
                {
                    "name": "get_comments",
                    "description": "Get comments for a specific recording (todo, message, etc.)"
                },
                {
                    "name": "create_comment",
                    "description": "Create a comment on a recording"
                },
                {
                    "name": "update_comment",
                    "description": "Update a comment"
                },
                {
                    "name": "delete_comment",
                    "description": "Delete a comment"
                },
                {
                    "name": "search_all",
                    "description": "Search across all Basecamp resources"
                }
            ]
        })
    except Exception as e:
        logger.error(f"Error in mcp_info: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# MCP Action endpoint with improved error handling
@app.route('/mcp/action', methods=['POST'])
def mcp_action():
    """
    Handle direct MCP actions without connection management.
    This is a simpler interface for testing and direct integration.
    
    Note: The connection-based approach using /initiate_connection and /tool/<connection_id>
    is preferred as it provides better error handling and state management.
    """
    logger.info("MCP action endpoint called")
    
    try:
        data = request.json
        action = data.get('action')
        params = data.get('params', {})
        
        logger.info(f"Action requested: {action}")
        
        # First check if we have a valid OAuth token
        token_data = token_storage.get_token()
        if not token_data or not token_data.get('access_token'):
            logger.error("No OAuth token available for action")
            return jsonify({
                "status": "error",
                "error": "authentication_required",
                "message": "OAuth authentication required. Please authenticate using the OAuth app first.",
                "oauth_url": "http://localhost:8000/"
            })
        
        # Check if token is expired
        if token_storage.is_token_expired():
            logger.info("Token expired, attempting to refresh")
            new_token = refresh_oauth_token()
            if not new_token:
                logger.error("Failed to refresh token")
                return jsonify({
                    "status": "error",
                    "error": "token_expired",
                    "message": "OAuth token has expired and could not be refreshed. Please authenticate again.",
                    "oauth_url": "http://localhost:8000/"
                })
        
        # Handle action based on type
        try:
            if action == 'get_projects':
                client = get_basecamp_client(auth_mode='oauth')
                projects = client.get_projects()
                return jsonify({
                    "status": "success",
                    "projects": projects,
                    "count": len(projects)
                })
            
            elif action == 'search':
                client = get_basecamp_client(auth_mode='oauth')
                search = BasecampSearch(client=client)
                
                query = params.get('query', '')
                include_completed = params.get('include_completed', False)
                
                logger.info(f"Searching with query: {query}")
                
                results = {
                    "projects": search.search_projects(query),
                    "todos": search.search_todos(query, include_completed=include_completed),
                    "messages": search.search_messages(query),
                }
                
                return jsonify({
                    "status": "success",
                    "results": results
                })
            
            else:
                logger.error(f"Unknown action: {action}")
                return jsonify({
                    "status": "error",
                    "error": "unknown_action",
                    "message": f"Unknown action: {action}"
                })
                
        except Exception as action_error:
            logger.error(f"Error executing action {action}: {str(action_error)}")
            return jsonify({
                "status": "error",
                "error": "execution_failed",
                "message": str(action_error)
            })
            
    except Exception as e:
        logger.error(f"Error in MCP action endpoint: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/')
def home():
    """Home page for the MCP server."""
    return jsonify({
        "status": "ok",
        "service": "basecamp-mcp-server",
        "description": "MCP server for Basecamp 3 integration"
    })

@app.route('/check_required_parameters', methods=['POST'])
def check_required_parameters():
    """
    Check the required parameters for connecting to Basecamp.
    """
    logger.info("Checking required parameters for Basecamp")
    
    try:
        # For OAuth mode
        if token_storage.get_token():
            return jsonify({
                "parameters": []  # No parameters needed if we have a token
            })
        
        # Otherwise, we need OAuth credentials
        return jsonify({
            "parameters": [
                {
                    "name": "auth_mode",
                    "description": "Authentication mode (oauth or pat)",
                    "required": True
                }
            ]
        })
    except Exception as e:
        logger.error(f"Error checking required parameters: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/initiate_connection', methods=['POST'])
def initiate_connection():
    """
    Initiate a connection to Basecamp.
    """
    data = request.json
    auth_mode = data.get('auth_mode', 'oauth')
    
    logger.info(f"Initiating connection with auth_mode: {auth_mode}")
    
    try:
        # Check if we have credentials for the requested auth mode
        if auth_mode == 'oauth':
            # Check if we have a valid token
            token_data = token_storage.get_token()
            
            # If token missing or expired, but we have a refresh token, try refreshing
            if (not token_data or not token_data.get('access_token') or token_storage.is_token_expired()) and token_data and token_data.get('refresh_token'):
                logger.info("Token missing or expired, attempting to refresh")
                access_token = refresh_oauth_token()
                if access_token:
                    logger.info("Token refreshed successfully")
                    token_data = token_storage.get_token()  # Get the updated token data
            
            # After potential refresh, check if we have a valid token
            if not token_data or not token_data.get('access_token'):
                logger.error("No OAuth token available")
                return jsonify({
                    "error": "No OAuth token available. Please authenticate using the OAuth app first.",
                    "oauth_url": "http://localhost:8000/"
                }), 401
            
            # Create a connection ID
            connection_id = f"basecamp-oauth-{int(time.time())}"
            active_connections[connection_id] = {
                "auth_mode": "oauth",
                "created_at": time.time()
            }
            
            logger.info(f"Created connection {connection_id} with OAuth")
            
            return jsonify({
                "connection_id": connection_id,
                "status": "connected",
                "auth_mode": "oauth"
            })
        
        elif auth_mode == 'pat':
            # Check if we have PAT credentials
            username = os.environ.get('BASECAMP_USERNAME')
            token = os.environ.get('BASECAMP_TOKEN')
            
            if not username or not token:
                logger.error("Missing PAT credentials")
                return jsonify({
                    "error": "Missing Personal Access Token credentials. Please set BASECAMP_USERNAME and BASECAMP_TOKEN."
                }), 401
            
            # Create a connection ID
            connection_id = f"basecamp-pat-{int(time.time())}"
            active_connections[connection_id] = {
                "auth_mode": "pat",
                "created_at": time.time()
            }
            
            logger.info(f"Created connection {connection_id} with PAT")
            
            return jsonify({
                "connection_id": connection_id,
                "status": "connected",
                "auth_mode": "pat"
            })
        
        else:
            logger.error(f"Invalid auth mode: {auth_mode}")
            return jsonify({
                "error": f"Invalid auth mode: {auth_mode}"
            }), 400
    
    except Exception as e:
        logger.error(f"Error initiating connection: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

@app.route('/check_active_connection', methods=['POST'])
def check_active_connection():
    """
    Check if a connection is active.
    """
    data = request.json
    connection_id = data.get('connection_id')
    
    logger.info(f"Checking active connection: {connection_id}")
    
    if connection_id in active_connections:
        return jsonify({
            "connection_id": connection_id,
            "status": "active"
        })
    
    return jsonify({
        "connection_id": connection_id,
        "status": "inactive"
    })

@app.route('/tool/<connection_id>', methods=['POST'])
def tool(connection_id):
    """
    Handle tool calls from the MCP client.
    """
    data = request.json
    action = data.get('action')
    params = data.get('params', {})
    
    logger.info(f"Tool call: {connection_id} - {action} - {params}")
    
    # Check if the connection is active
    if connection_id not in active_connections:
        logger.error(f"Invalid connection ID: {connection_id}")
        return jsonify({
            "error": "Invalid connection ID"
        }), 401
    
    # Get the auth mode for this connection
    auth_mode = active_connections[connection_id].get('auth_mode', 'oauth')
    
    try:
        # Create a Basecamp client
        client = get_basecamp_client(auth_mode=auth_mode)
        
        # Handle different actions
        if action == 'get_projects':
            projects = client.get_projects()
            return jsonify({
                "projects": projects
            })
        
        elif action == 'get_project':
            project_id = params.get('project_id')
            if not project_id:
                return jsonify({"error": "Missing project_id parameter"}), 400
            
            project = client.get_project(project_id)
            return jsonify({
                "project": project
            })
        
        elif action == 'get_todolists':
            project_id = params.get('project_id')
            if not project_id:
                return jsonify({"error": "Missing project_id parameter"}), 400
            
            todolists = client.get_todolists(project_id)
            return jsonify({
                "todolists": todolists
            })
        
        elif action == 'get_todos':
            todolist_id = params.get('todolist_id')
            if not todolist_id:
                return jsonify({"error": "Missing todolist_id parameter"}), 400
            
            todos = client.get_todos(todolist_id)
            return jsonify({
                "todos": todos
            })
        
        elif action == 'create_todo':
            todolist_id = params.get('todolist_id')
            content = params.get('content')
            
            if not todolist_id or not content:
                return jsonify({"error": "Missing todolist_id or content parameter"}), 400
            
            todo = client.create_todo(
                todolist_id=todolist_id,
                content=content,
                description=params.get('description', ''),
                assignee_ids=params.get('assignee_ids', [])
            )
            
            return jsonify({
                "todo": todo
            })
        
        elif action == 'complete_todo':
            todo_id = params.get('todo_id')
            if not todo_id:
                return jsonify({"error": "Missing todo_id parameter"}), 400
            
            result = client.complete_todo(todo_id)
            return jsonify({
                "result": result
            })
        
        elif action == 'search':
            query = params.get('query')
            if not query:
                return jsonify({"error": "Missing query parameter"}), 400
            
            # Create search utility
            search = BasecampSearch(client=client)
            
            # Determine what to search
            types = params.get('types', ['projects', 'todos', 'messages'])
            include_completed = params.get('include_completed', False)
            
            results = {}
            
            if 'projects' in types:
                results['projects'] = search.search_projects(query)
            
            if 'todos' in types:
                results['todos'] = search.search_todos(query, include_completed=include_completed)
            
            if 'messages' in types:
                results['messages'] = search.search_messages(query)
            
            return jsonify({
                "results": results
            })
        
        else:
            logger.error(f"Unknown action: {action}")
            return jsonify({
                "error": f"Unknown action: {action}"
            }), 400
    
    except Exception as e:
        logger.error(f"Error handling tool call: {str(e)}")
        return jsonify({
            "error": str(e)
        }), 500

if __name__ == '__main__':
    try:
        logger.info(f"Starting MCP server on port {MCP_PORT}")
        logger.info("Press Ctrl+C to stop the server")
        
        # Run the Flask app
        # Disable debug and auto-reloader when running in production or background
        is_debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
        
        logger.info("Running in %s mode", "debug" if is_debug else "production")
        app.run(
            host='0.0.0.0',
            port=MCP_PORT,
            debug=is_debug,
            use_reloader=is_debug,
            threaded=True,
        )
    except Exception as e:
        logger.error(f"Error starting server: {str(e)}", exc_info=True)
        sys.exit(1) 