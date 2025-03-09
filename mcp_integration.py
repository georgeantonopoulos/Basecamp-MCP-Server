"""
Basecamp 2.4.2 MCP Integration Module

This module provides Multi-Cloud Provider (MCP) compatible functions for integrating
with Basecamp 2.4.2 API. It can be used as a starting point for creating a full
MCP connector.
"""

import os
from dotenv import load_dotenv
from basecamp_client import BasecampClient
from search_utils import BasecampSearch

# Load environment variables
load_dotenv()

# MCP Authentication Functions

def get_required_parameters(params):
    """
    Get the required parameters for connecting to Basecamp 2.4.2.
    
    For Basic Authentication, we need:
    - username
    - password
    - account_id
    - user_agent
    
    Returns:
        dict: Dictionary of required parameters
    """
    return {
        "required_parameters": [
            {
                "name": "username",
                "description": "Your Basecamp username (email)",
                "type": "string"
            },
            {
                "name": "password",
                "description": "Your Basecamp password",
                "type": "string",
                "sensitive": True
            },
            {
                "name": "account_id",
                "description": "Your Basecamp account ID (the number in your Basecamp URL)",
                "type": "string"
            },
            {
                "name": "user_agent",
                "description": "User agent for API requests (e.g., 'YourApp (your-email@example.com)')",
                "type": "string",
                "default": f"MCP Basecamp Connector ({os.getenv('BASECAMP_USERNAME', 'your-email@example.com')})"
            }
        ]
    }

def initiate_connection(params):
    """
    Initiate a connection to Basecamp 2.4.2.
    
    Args:
        params (dict): Connection parameters including:
            - username: Basecamp username (email)
            - password: Basecamp password
            - account_id: Basecamp account ID
            - user_agent: User agent for API requests
            
    Returns:
        dict: Connection details and status
    """
    parameters = params.get("parameters", {})
    username = parameters.get("username")
    password = parameters.get("password")
    account_id = parameters.get("account_id")
    user_agent = parameters.get("user_agent")
    
    try:
        client = BasecampClient(
            username=username,
            password=password,
            account_id=account_id,
            user_agent=user_agent
        )
        
        success, message = client.test_connection()
        
        if success:
            return {
                "status": "connected",
                "connection_id": f"basecamp_{account_id}",
                "message": "Successfully connected to Basecamp"
            }
        else:
            return {
                "status": "error",
                "message": message
            }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def check_active_connection(params):
    """
    Check if a connection to Basecamp is active.
    
    Args:
        params (dict): Parameters containing:
            - connection_id: The connection ID to check
            
    Returns:
        dict: Status of the connection
    """
    # This is a placeholder. In a real implementation, you would check if the
    # connection is still valid, possibly by making a simple API call.
    return {
        "status": "active", 
        "message": "Connection is active"
    }

# MCP Core Functions

def get_projects(params):
    """
    Get all projects from Basecamp.
    
    Args:
        params (dict): Parameters including:
            - query (optional): Filter projects by name
            
    Returns:
        dict: List of projects
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Set up the search utility
    search = BasecampSearch(client=client)
    
    # Get the query parameter
    query = params.get("query")
    
    # Search for projects
    projects = search.search_projects(query)
    
    return {
        "status": "success",
        "count": len(projects),
        "projects": projects
    }

def get_todo_lists(params):
    """
    Get all to-do lists from a project.
    
    Args:
        params (dict): Parameters including:
            - project_id: The project ID
            - query (optional): Filter to-do lists by name
            
    Returns:
        dict: List of to-do lists
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Set up the search utility
    search = BasecampSearch(client=client)
    
    # Get the parameters
    project_id = params.get("project_id")
    query = params.get("query")
    
    # Validate required parameters
    if not project_id:
        return {
            "status": "error",
            "message": "project_id is required"
        }
    
    # Search for to-do lists
    todolists = search.search_todolists(query, project_id)
    
    return {
        "status": "success",
        "count": len(todolists),
        "todolists": todolists
    }

def get_todos(params):
    """
    Get all to-dos with various filters.
    
    Args:
        params (dict): Parameters including:
            - project_id (optional): Filter by project ID
            - todolist_id (optional): Filter by to-do list ID
            - query (optional): Filter to-dos by content
            - include_completed (optional): Include completed to-dos
            
    Returns:
        dict: List of to-dos
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Set up the search utility
    search = BasecampSearch(client=client)
    
    # Get the parameters
    project_id = params.get("project_id")
    todolist_id = params.get("todolist_id")
    query = params.get("query")
    include_completed = params.get("include_completed", False)
    
    # Search for to-dos
    todos = search.search_todos(
        query=query,
        project_id=project_id,
        todolist_id=todolist_id,
        include_completed=include_completed
    )
    
    return {
        "status": "success",
        "count": len(todos),
        "todos": todos
    }

def get_comments(params):
    """
    Get comments for a specific recording (todo, message, etc.).
    
    Args:
        params (dict): Parameters including:
            - recording_id (required): ID of the recording (todo, message, etc.)
            - bucket_id (required): Project/bucket ID
            - query (optional): Filter comments by content
            
    Returns:
        dict: List of comments
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Set up the search utility
    search = BasecampSearch(client=client)
    
    # Get the parameters
    recording_id = params.get("recording_id")
    bucket_id = params.get("bucket_id")
    query = params.get("query")
    
    # Validate required parameters
    if not recording_id or not bucket_id:
        return {
            "status": "error",
            "message": "recording_id and bucket_id are required"
        }
    
    # Search for comments
    comments = search.search_comments(
        query=query,
        recording_id=recording_id,
        bucket_id=bucket_id
    )
    
    return {
        "status": "success",
        "count": len(comments),
        "comments": comments
    }

def create_comment(params):
    """
    Create a comment on a recording.
    
    Args:
        params (dict): Parameters including:
            - recording_id (required): ID of the recording to comment on
            - bucket_id (required): Project/bucket ID
            - content (required): Content of the comment in HTML format
            
    Returns:
        dict: The created comment
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Get the parameters
    recording_id = params.get("recording_id")
    bucket_id = params.get("bucket_id")
    content = params.get("content")
    
    # Validate required parameters
    if not recording_id or not bucket_id:
        return {
            "status": "error",
            "message": "recording_id and bucket_id are required"
        }
    
    if not content:
        return {
            "status": "error",
            "message": "content is required"
        }
    
    try:
        # Create the comment
        comment = client.create_comment(recording_id, bucket_id, content)
        
        return {
            "status": "success",
            "comment": comment
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def update_comment(params):
    """
    Update a comment.
    
    Args:
        params (dict): Parameters including:
            - comment_id (required): Comment ID
            - bucket_id (required): Project/bucket ID
            - content (required): New content for the comment in HTML format
            
    Returns:
        dict: The updated comment
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Get the parameters
    comment_id = params.get("comment_id")
    bucket_id = params.get("bucket_id")
    content = params.get("content")
    
    # Validate required parameters
    if not comment_id or not bucket_id:
        return {
            "status": "error",
            "message": "comment_id and bucket_id are required"
        }
    
    if not content:
        return {
            "status": "error",
            "message": "content is required"
        }
    
    try:
        # Update the comment
        comment = client.update_comment(comment_id, bucket_id, content)
        
        return {
            "status": "success",
            "comment": comment
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def delete_comment(params):
    """
    Delete a comment.
    
    Args:
        params (dict): Parameters including:
            - comment_id (required): Comment ID
            - bucket_id (required): Project/bucket ID
            
    Returns:
        dict: Status of the operation
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Get the parameters
    comment_id = params.get("comment_id")
    bucket_id = params.get("bucket_id")
    
    # Validate required parameters
    if not comment_id or not bucket_id:
        return {
            "status": "error",
            "message": "comment_id and bucket_id are required"
        }
    
    try:
        # Delete the comment
        success = client.delete_comment(comment_id, bucket_id)
        
        if success:
            return {
                "status": "success",
                "message": "Comment deleted successfully"
            }
        else:
            return {
                "status": "error",
                "message": "Failed to delete comment"
            }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

def search_all(params):
    """
    Search across all Basecamp resources.
    
    Args:
        params (dict): Parameters including:
            - query: The search query
            - resource_types (optional): Types of resources to search (projects, todolists, todos)
            - include_completed (optional): Include completed to-dos
            
    Returns:
        dict: Search results grouped by resource type
    """
    # Get the client
    client = _get_client_from_params(params)
    
    # Set up the search utility
    search = BasecampSearch(client=client)
    
    # Get the parameters
    query = params.get("query")
    resource_types = params.get("resource_types", ["projects", "todolists", "todos"])
    include_completed = params.get("include_completed", False)
    
    # Validate required parameters
    if not query:
        return {
            "status": "error",
            "message": "query is required"
        }
    
    # Initialize results
    results = {
        "status": "success",
        "query": query,
        "results": {}
    }
    
    # Search based on resource types
    if "projects" in resource_types:
        projects = search.search_projects(query)
        results["results"]["projects"] = {
            "count": len(projects),
            "items": projects
        }
    
    if "todolists" in resource_types:
        todolists = search.search_todolists(query)
        results["results"]["todolists"] = {
            "count": len(todolists),
            "items": todolists
        }
    
    if "todos" in resource_types:
        todos = search.search_todos(query=query, include_completed=include_completed)
        results["results"]["todos"] = {
            "count": len(todos),
            "items": todos
        }
    
    # Calculate total count
    total_count = sum(
        results["results"][resource]["count"] 
        for resource in results["results"]
    )
    results["total_count"] = total_count
    
    return results

# Helper functions

def _get_client_from_params(params):
    """
    Get a BasecampClient instance from the given parameters.
    
    Args:
        params (dict): Parameters including:
            - connection_id (optional): Connection ID for the client
            - oauth_mode (optional): Whether to use OAuth for authentication
            - access_token (optional): OAuth access token
            - username (optional): Basic Auth username
            - password (optional): Basic Auth password
            - account_id (optional): Account ID
            - user_agent (optional): User agent for API requests
            
    Returns:
        BasecampClient: A configured client
    """
    # Mock connection for testing - return a fake client
    if params.get("connection_id") and params.get("connection_id").startswith("mock_"):
        print(f"Using mock client for connection ID: {params.get('connection_id')}")
        from unittest.mock import MagicMock
        mock_client = MagicMock()
        
        # Set up mock responses for known methods
        mock_client.get_projects.return_value = [{"id": 123, "name": "Mock Project"}]
        mock_client.get_comments.return_value = [{"id": 456, "content": "Mock comment"}]
        mock_client.create_comment.return_value = {"id": 789, "content": "New mock comment"}
        mock_client.update_comment.return_value = {"id": 789, "content": "Updated mock comment"}
        mock_client.delete_comment.return_value = True
        
        return mock_client
    
    # Check if OAuth mode is specified
    oauth_mode = params.get("oauth_mode", False)
    
    if oauth_mode:
        # OAuth authentication
        access_token = params.get("access_token") or os.getenv("BASECAMP_ACCESS_TOKEN")
        account_id = params.get("account_id") or os.getenv("BASECAMP_ACCOUNT_ID")
        user_agent = params.get("user_agent") or os.getenv("USER_AGENT")
        
        if not all([access_token, account_id, user_agent]):
            raise ValueError("Missing required OAuth credentials. Please provide access_token, account_id, and user_agent.")
            
        return BasecampClient(
            access_token=access_token,
            account_id=account_id,
            user_agent=user_agent,
            auth_mode="oauth"
        )
    else:
        # Basic authentication
        username = params.get("username") or os.getenv("BASECAMP_USERNAME")
        password = params.get("password") or os.getenv("BASECAMP_PASSWORD")
        account_id = params.get("account_id") or os.getenv("BASECAMP_ACCOUNT_ID")
        user_agent = params.get("user_agent") or os.getenv("USER_AGENT")
        
        if not all([username, password, account_id, user_agent]):
            raise ValueError("Missing required Basic Auth credentials. Please provide username, password, account_id, and user_agent.")
            
        return BasecampClient(
            username=username,
            password=password,
            account_id=account_id,
            user_agent=user_agent,
            auth_mode="basic"
        ) 