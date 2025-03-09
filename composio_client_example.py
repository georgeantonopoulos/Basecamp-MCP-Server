#!/usr/bin/env python
"""
Example client for using the Basecamp MCP server with Composio.
This example demonstrates MCP protocol integration requirements.
"""
import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
MCP_SERVER_URL = "http://localhost:5001"
COMPOSIO_API_KEY = os.getenv("COMPOSIO_API_KEY")

class BasecampComposioClient:
    """A client for interacting with Basecamp through Composio's MCP protocol."""
    
    def __init__(self, mcp_server_url=MCP_SERVER_URL):
        """Initialize the client with the MCP server URL."""
        self.mcp_server_url = mcp_server_url
        self.headers = {
            "Content-Type": "application/json"
        }
        # Add Composio API key if available
        if COMPOSIO_API_KEY:
            self.headers["X-Composio-API-Key"] = COMPOSIO_API_KEY
    
    def check_auth(self):
        """Check if OAuth authentication is available."""
        response = requests.get(
            f"{self.mcp_server_url}/composio/check_auth",
            headers=self.headers
        )
        return response.json()
    
    def get_schema(self):
        """Get the schema of available tools."""
        response = requests.get(
            f"{self.mcp_server_url}/composio/schema",
            headers=self.headers
        )
        return response.json()
    
    def execute_tool(self, tool_name, params=None):
        """Execute a tool with the given parameters."""
        if params is None:
            params = {}
            
        response = requests.post(
            f"{self.mcp_server_url}/composio/tool",
            headers=self.headers,
            json={"tool": tool_name, "params": params}
        )
        return response.json()
    
    def get_projects(self):
        """Get all projects from Basecamp."""
        return self.execute_tool("GET_PROJECTS")
    
    def get_project(self, project_id):
        """Get details for a specific project."""
        return self.execute_tool("GET_PROJECT", {"project_id": project_id})
    
    def get_todolists(self, project_id):
        """Get all todo lists for a project."""
        return self.execute_tool("GET_TODOLISTS", {"project_id": project_id})
    
    def get_todos(self, todolist_id):
        """Get all todos for a specific todolist."""
        return self.execute_tool("GET_TODOS", {"todolist_id": todolist_id})
    
    def get_campfire(self, project_id):
        """Get all chat rooms (campfires) for a project."""
        return self.execute_tool("GET_CAMPFIRE", {"project_id": project_id})
    
    def get_campfire_lines(self, project_id, campfire_id):
        """Get messages from a specific chat room."""
        return self.execute_tool("GET_CAMPFIRE_LINES", {
            "project_id": project_id,
            "campfire_id": campfire_id
        })
    
    def search(self, query, project_id=None):
        """Search across Basecamp resources."""
        params = {"query": query}
        if project_id:
            params["project_id"] = project_id
        return self.execute_tool("SEARCH", params)
    
    def get_comments(self, recording_id, bucket_id):
        """Get comments for a specific Basecamp object."""
        return self.execute_tool("GET_COMMENTS", {
            "recording_id": recording_id,
            "bucket_id": bucket_id
        })
    
    def create_comment(self, recording_id, bucket_id, content):
        """Create a new comment on a Basecamp object."""
        return self.execute_tool("CREATE_COMMENT", {
            "recording_id": recording_id,
            "bucket_id": bucket_id,
            "content": content
        })

def main():
    """Main function to demonstrate the client."""
    client = BasecampComposioClient()
    
    # Verify connectivity to MCP server
    print("==== Basecamp MCP-Composio Integration Test ====")
    
    # Check authentication
    print("\n1. Checking authentication status...")
    auth_status = client.check_auth()
    print(f"Authentication Status: {json.dumps(auth_status, indent=2)}")
    
    if auth_status.get("status") == "error":
        print(f"Please authenticate at: {auth_status.get('error', {}).get('auth_url', '')}")
        return
    
    # Get available tools
    print("\n2. Retrieving tool schema...")
    schema = client.get_schema()
    print(f"Server Name: {schema.get('name')}")
    print(f"Version: {schema.get('version')}")
    print(f"Authentication Type: {schema.get('auth', {}).get('type')}")
    print("\nAvailable Tools:")
    for tool in schema.get("tools", []):
        required_params = tool.get("parameters", {}).get("required", [])
        required_str = ", ".join(required_params) if required_params else "None"
        print(f"- {tool['name']}: {tool['description']} (Required params: {required_str})")
    
    # Get projects
    print("\n3. Fetching projects...")
    projects_response = client.get_projects()
    
    if projects_response.get("status") == "error":
        print(f"Error: {projects_response.get('error', {}).get('message', 'Unknown error')}")
    else:
        project_data = projects_response.get("data", [])
        print(f"Found {len(project_data)} projects:")
        for i, project in enumerate(project_data[:3], 1):  # Show first 3 projects
            print(f"{i}. {project.get('name')} (ID: {project.get('id')})")
        
        if project_data:
            # Use the first project for further examples
            project_id = project_data[0].get("id")
            
            # Get campfires for the project
            print(f"\n4. Fetching campfires for project {project_id}...")
            campfires_response = client.get_campfire(project_id)
            
            if campfires_response.get("status") == "error":
                print(f"Error: {campfires_response.get('error', {}).get('message', 'Unknown error')}")
            else:
                campfire_data = campfires_response.get("data", {}).get("campfire", [])
                print(f"Found {len(campfire_data)} campfires:")
                for i, campfire in enumerate(campfire_data[:2], 1):  # Show first 2 campfires
                    print(f"{i}. {campfire.get('title')} (ID: {campfire.get('id')})")
                
                if campfire_data:
                    # Get messages from the first campfire
                    campfire_id = campfire_data[0].get("id")
                    print(f"\n5. Fetching messages from campfire {campfire_id}...")
                    messages_response = client.get_campfire_lines(project_id, campfire_id)
                    
                    if messages_response.get("status") == "error":
                        print(f"Error: {messages_response.get('error', {}).get('message', 'Unknown error')}")
                    else:
                        message_data = messages_response.get("data", {}).get("lines", [])
                        print(f"Found {len(message_data)} messages:")
                        for i, message in enumerate(message_data[:3], 1):  # Show first 3 messages
                            creator = message.get("creator", {}).get("name", "Unknown")
                            content = message.get("title", "No content")
                            print(f"{i}. From {creator}: {content[:50]}...")

    print("\n==== Test completed ====")
    print("This example demonstrates how to connect to the Basecamp MCP server")
    print("and use it with the Composio MCP protocol.")

if __name__ == "__main__":
    main() 