#!/usr/bin/env python3
"""
Example of using the Basecamp Card Table API through the MCP integration.

This example demonstrates how to:
1. Get a card table for a project
2. List columns
3. Create a new column
4. Create cards in columns
5. Move cards between columns
6. Update column properties
"""

import json
import subprocess
import sys

def send_mcp_request(method, params=None):
    """Send a request to the MCP server and return the response."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    
    # Run the MCP server with the request
    process = subprocess.Popen(
        [sys.executable, "mcp_server_cli.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    stdout, stderr = process.communicate(input=json.dumps(request))
    
    if process.returncode != 0:
        print(f"Error: {stderr}")
        return None
    
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        print(f"Failed to parse response: {e}")
        print(f"Response: {stdout}")
        return None

def main():
    """Demonstrate card table functionality."""
    
    # Example project ID - replace with your actual project ID
    project_id = "123456"
    
    print("Basecamp Card Table Example")
    print("=" * 50)
    
    # 1. Get the card table for a project
    print("\n1. Getting card table for project...")
    response = send_mcp_request("tools/call", {
        "name": "get_card_table",
        "arguments": {"project_id": project_id}
    })
    
    if response and "result" in response:
        result = json.loads(response["result"]["content"][0]["text"])
        if result.get("status") == "success":
            card_table = result["card_table"]
            card_table_id = card_table["id"]
            print(f"Card table found: {card_table['title']} (ID: {card_table_id})")
        else:
            print("No card table found. Make sure the Card Table tool is enabled in your project.")
            return
    
    # 2. List existing columns
    print("\n2. Listing columns...")
    response = send_mcp_request("tools/call", {
        "name": "get_columns",
        "arguments": {
            "project_id": project_id,
            "card_table_id": card_table_id
        }
    })
    
    if response and "result" in response:
        result = json.loads(response["result"]["content"][0]["text"])
        columns = result.get("columns", [])
        print(f"Found {len(columns)} columns:")
        for col in columns:
            print(f"  - {col['title']} (ID: {col['id']})")
    
    # 3. Create a new column
    print("\n3. Creating a new column...")
    response = send_mcp_request("tools/call", {
        "name": "create_column",
        "arguments": {
            "project_id": project_id,
            "card_table_id": card_table_id,
            "title": "Testing"
        }
    })
    
    if response and "result" in response:
        result = json.loads(response["result"]["content"][0]["text"])
        if result.get("status") == "success":
            new_column = result["column"]
            print(f"Created column: {new_column['title']} (ID: {new_column['id']})")
    
    # 4. Create a card in the first column
    if columns:
        first_column_id = columns[0]['id']
        print(f"\n4. Creating a card in column '{columns[0]['title']}'...")
        
        response = send_mcp_request("tools/call", {
            "name": "create_card",
            "arguments": {
                "project_id": project_id,
                "column_id": first_column_id,
                "title": "Test Card",
                "content": "This is a test card created via the MCP API"
            }
        })
        
        if response and "result" in response:
            result = json.loads(response["result"]["content"][0]["text"])
            if result.get("status") == "success":
                new_card = result["card"]
                print(f"Created card: {new_card['title']} (ID: {new_card['id']})")
    
    # 5. Update column color
    if columns:
        print(f"\n5. Updating color of column '{columns[0]['title']}'...")
        
        response = send_mcp_request("tools/call", {
            "name": "update_column_color",
            "arguments": {
                "project_id": project_id,
                "column_id": columns[0]['id'],
                "color": "#FF0000"  # Red
            }
        })
        
        if response and "result" in response:
            result = json.loads(response["result"]["content"][0]["text"])
            if result.get("status") == "success":
                print(f"Updated column color to red")
    
    print("\n" + "=" * 50)
    print("Example completed!")
    print("\nNote: Replace the project_id with your actual Basecamp project ID to run this example.")

if __name__ == "__main__":
    main()