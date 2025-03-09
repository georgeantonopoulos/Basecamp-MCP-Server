#!/usr/bin/env python
import os
import json
import logging
from flask import Flask, request, jsonify
from basecamp_client import BasecampClient
from search_utils import BasecampSearch
import token_storage
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def get_basecamp_client(auth_mode='oauth'):
    """
    Returns a BasecampClient instance with appropriate authentication.
    
    Args:
        auth_mode (str): The authentication mode to use ('oauth' or 'basic')
        
    Returns:
        BasecampClient: A client for interacting with Basecamp
    """
    if auth_mode == 'oauth':
        # Get the OAuth token
        token_data = token_storage.get_token()
        if not token_data or 'access_token' not in token_data:
            logger.error("No OAuth token available")
            return None
            
        # Create a client using the OAuth token
        account_id = os.getenv('BASECAMP_ACCOUNT_ID')
        user_agent = os.getenv('USER_AGENT')
        client = BasecampClient(
            account_id=account_id,
            user_agent=user_agent,
            access_token=token_data['access_token'],
            auth_mode='oauth'
        )
        return client
    else:
        # Basic auth is not recommended but keeping for compatibility
        username = os.getenv('BASECAMP_USERNAME')
        password = os.getenv('BASECAMP_PASSWORD')
        account_id = os.getenv('BASECAMP_ACCOUNT_ID')
        user_agent = os.getenv('USER_AGENT')
        
        client = BasecampClient(
            username=username,
            password=password,
            account_id=account_id,
            user_agent=user_agent,
            auth_mode='basic'
        )
        return client

def get_schema():
    """
    Returns the schema for Basecamp tools compatible with Composio's MCP format.
    
    Returns:
        dict: A schema describing available tools and their parameters according to Composio specs
    """
    schema = {
        "name": "Basecamp MCP Server",
        "description": "Integration with Basecamp 3 for project management and team collaboration",
        "version": "1.0.0", 
        "auth": {
            "type": "oauth2",
            "redirect_url": "http://localhost:8000",
            "token_url": "http://localhost:8000/token/info"
        },
        "contact": {
            "name": "Basecamp MCP Server Team",
            "url": "https://github.com/georgeantonopoulos/Basecamp-MCP-Server"
        },
        "tools": [
            {
                "name": "GET_PROJECTS",
                "description": "Get all projects from Basecamp",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "GET_PROJECT",
                "description": "Get details for a specific project",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The ID of the project"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "GET_TODOLISTS",
                "description": "Get all todo lists for a project",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The ID of the project"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "GET_TODOS",
                "description": "Get all todos for a specific todolist",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "todolist_id": {"type": "string", "description": "The ID of the todolist"}
                    },
                    "required": ["todolist_id"]
                }
            },
            {
                "name": "GET_CAMPFIRE",
                "description": "Get all chat rooms (campfires) for a project",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The ID of the project"}
                    },
                    "required": ["project_id"]
                }
            },
            {
                "name": "GET_CAMPFIRE_LINES",
                "description": "Get messages from a specific chat room",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "project_id": {"type": "string", "description": "The ID of the project"},
                        "campfire_id": {"type": "string", "description": "The ID of the campfire/chat room"}
                    },
                    "required": ["project_id", "campfire_id"]
                }
            },
            {
                "name": "SEARCH",
                "description": "Search across Basecamp resources",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query"},
                        "project_id": {"type": "string", "description": "Optional project ID to limit search scope"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "GET_COMMENTS",
                "description": "Get comments for a specific Basecamp object",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "recording_id": {"type": "string", "description": "The ID of the object to get comments for"},
                        "bucket_id": {"type": "string", "description": "The bucket ID"}
                    },
                    "required": ["recording_id", "bucket_id"]
                }
            },
            {
                "name": "CREATE_COMMENT",
                "description": "Create a new comment on a Basecamp object",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "recording_id": {"type": "string", "description": "The ID of the object to comment on"},
                        "bucket_id": {"type": "string", "description": "The bucket ID"},
                        "content": {"type": "string", "description": "The comment content"}
                    },
                    "required": ["recording_id", "bucket_id", "content"]
                }
            }
        ]
    }
    return schema

def handle_composio_request(data):
    """
    Handle a request from Composio following MCP standards.
    
    Args:
        data (dict): The request data containing tool name and parameters
        
    Returns:
        dict: The result of the tool execution in MCP-compliant format
    """
    # Check if the API key is valid (if provided)
    composio_api_key = os.getenv('COMPOSIO_API_KEY')
    request_api_key = request.headers.get('X-Composio-API-Key')
    
    if composio_api_key and request_api_key and composio_api_key != request_api_key:
        return {
            "status": "error",
            "error": {
                "type": "authentication_error",
                "message": "Invalid API key provided"
            }
        }
    
    tool_name = data.get('tool')
    params = data.get('params', {})
    
    # Get a Basecamp client
    client = get_basecamp_client(auth_mode='oauth')
    if not client:
        return {
            "status": "error",
            "error": {
                "type": "authentication_required",
                "message": "OAuth authentication required",
                "auth_url": "http://localhost:8000/"
            }
        }
    
    # Route to the appropriate handler based on tool_name
    try:
        if tool_name == "GET_PROJECTS":
            result = client.get_projects()
            return {
                "status": "success",
                "data": result
            }
            
        elif tool_name == "GET_PROJECT":
            project_id = params.get('project_id')
            if not project_id:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameter: project_id"
                    }
                }
            result = client.get_project(project_id)
            return {
                "status": "success",
                "data": result
            }
            
        elif tool_name == "GET_TODOLISTS":
            project_id = params.get('project_id')
            if not project_id:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameter: project_id"
                    }
                }
            result = client.get_todolists(project_id)
            return {
                "status": "success",
                "data": result
            }
            
        elif tool_name == "GET_TODOS":
            todolist_id = params.get('todolist_id')
            if not todolist_id:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameter: todolist_id"
                    }
                }
            result = client.get_todos(todolist_id)
            return {
                "status": "success",
                "data": result
            }
            
        elif tool_name == "GET_CAMPFIRE":
            project_id = params.get('project_id')
            if not project_id:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameter: project_id"
                    }
                }
            result = client.get_campfires(project_id)
            return {
                "status": "success",
                "data": {
                    "campfire": result
                }
            }
            
        elif tool_name == "GET_CAMPFIRE_LINES":
            project_id = params.get('project_id')
            campfire_id = params.get('campfire_id')
            if not project_id or not campfire_id:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameters: project_id and/or campfire_id"
                    }
                }
            result = client.get_campfire_lines(project_id, campfire_id)
            return {
                "status": "success",
                "data": result
            }
            
        elif tool_name == "SEARCH":
            query = params.get('query')
            project_id = params.get('project_id')
            if not query:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameter: query"
                    }
                }
            
            search = BasecampSearch(client=client)
            results = []
            
            # Search projects
            if not project_id:
                projects = search.search_projects(query)
                if projects:
                    results.extend([{"type": "project", "data": p} for p in projects])
            
            # If project_id is provided, search within that project
            if project_id:
                # Search todolists
                todolists = search.search_todolists(query, project_id)
                if todolists:
                    results.extend([{"type": "todolist", "data": t} for t in todolists])
                
                # Search todos
                todos = search.search_todos(query, project_id)
                if todos:
                    results.extend([{"type": "todo", "data": t} for t in todos])
                
                # Search campfire lines
                campfires = client.get_campfires(project_id)
                for campfire in campfires:
                    campfire_id = campfire.get('id')
                    lines = search.search_campfire_lines(query, project_id, campfire_id)
                    if lines:
                        results.extend([{"type": "campfire_line", "data": l} for l in lines])
            
            return {
                "status": "success",
                "data": {
                    "results": results,
                    "count": len(results)
                }
            }
            
        elif tool_name == "GET_COMMENTS":
            recording_id = params.get('recording_id')
            bucket_id = params.get('bucket_id')
            if not recording_id or not bucket_id:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameters: recording_id and/or bucket_id"
                    }
                }
            result = client.get_comments(recording_id, bucket_id)
            return {
                "status": "success",
                "data": result
            }
            
        elif tool_name == "CREATE_COMMENT":
            recording_id = params.get('recording_id')
            bucket_id = params.get('bucket_id')
            content = params.get('content')
            if not recording_id or not bucket_id or not content:
                return {
                    "status": "error",
                    "error": {
                        "type": "invalid_parameters",
                        "message": "Missing required parameters"
                    }
                }
            result = client.create_comment(recording_id, bucket_id, content)
            return {
                "status": "success",
                "data": result
            }
            
        else:
            return {
                "status": "error",
                "error": {
                    "type": "unknown_tool",
                    "message": f"Unknown tool: {tool_name}"
                }
            }
            
    except Exception as e:
        logger.error(f"Error handling tool {tool_name}: {str(e)}")
        return {
            "status": "error",
            "error": {
                "type": "server_error",
                "message": f"Error executing tool: {str(e)}"
            }
        } 