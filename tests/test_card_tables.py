#!/usr/bin/env python3
"""
Test script for Card Table functionality in Basecamp MCP integration.
"""

import json
import sys
import os
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from mcp_server_cli import MCPServer
from basecamp_client import BasecampClient


class TestCardTableTools(unittest.TestCase):
    """Test Card Table MCP tools."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.server = MCPServer()
        
    def test_card_table_tools_registered(self):
        """Test that all card table tools are registered."""
        tool_names = [tool['name'] for tool in self.server.tools]
        
        expected_tools = [
            'get_card_table',
            'get_columns',
            'get_column',
            'create_column',
            'update_column',
            'move_column',
            'update_column_color',
            'put_column_on_hold',
            'remove_column_hold',
            'watch_column',
            'unwatch_column',
            'get_cards',
            'get_card',
            'create_card',
            'update_card',
            'move_card'
        ]
        
        for tool in expected_tools:
            self.assertIn(tool, tool_names, f"Tool '{tool}' not found in registered tools")
    
    def test_tool_schemas(self):
        """Test that tool schemas are properly defined."""
        tools_by_name = {tool['name']: tool for tool in self.server.tools}
        
        # Test get_card_table schema
        schema = tools_by_name['get_card_table']['inputSchema']
        self.assertEqual(schema['type'], 'object')
        self.assertIn('project_id', schema['properties'])
        self.assertIn('project_id', schema['required'])
        
        # Test create_card schema
        schema = tools_by_name['create_card']['inputSchema']
        self.assertEqual(schema['type'], 'object')
        self.assertIn('project_id', schema['properties'])
        self.assertIn('column_id', schema['properties'])
        self.assertIn('title', schema['properties'])
        self.assertIn('content', schema['properties'])
        self.assertIn('project_id', schema['required'])
        self.assertIn('column_id', schema['required'])
        self.assertIn('title', schema['required'])
        self.assertNotIn('content', schema['required'])  # content is optional
        
    @patch('mcp_server_cli.token_storage.get_token')
    @patch('mcp_server_cli.token_storage.is_token_expired')
    def test_execute_get_card_table(self, mock_expired, mock_get_token):
        """Test executing get_card_table tool."""
        mock_expired.return_value = False
        mock_get_token.return_value = {
            'access_token': 'test_token',
            'account_id': '12345'
        }
        
        with patch.object(BasecampClient, 'get_card_table') as mock_get_table:
            with patch.object(BasecampClient, 'get_card_table_details') as mock_get_details:
                mock_get_table.return_value = {'id': '123', 'name': 'card_table'}
                mock_get_details.return_value = {
                    'id': '123',
                    'name': 'card_table',
                    'title': 'Card Table',
                    'columns_count': 4
                }
                
                result = self.server._execute_tool('get_card_table', {'project_id': '456'})
                
                self.assertEqual(result['status'], 'success')
                self.assertIn('card_table', result)
                self.assertEqual(result['card_table']['id'], '123')
                
    @patch('mcp_server_cli.token_storage.get_token')
    @patch('mcp_server_cli.token_storage.is_token_expired')
    def test_execute_create_card(self, mock_expired, mock_get_token):
        """Test executing create_card tool."""
        mock_expired.return_value = False
        mock_get_token.return_value = {
            'access_token': 'test_token',
            'account_id': '12345'
        }
        
        with patch.object(BasecampClient, 'create_card') as mock_create:
            mock_create.return_value = {
                'id': '789',
                'title': 'New Card',
                'content': 'Card content',
                'column_id': '456'
            }
            
            result = self.server._execute_tool('create_card', {
                'project_id': '123',
                'column_id': '456',
                'title': 'New Card',
                'content': 'Card content'
            })
            
            self.assertEqual(result['status'], 'success')
            self.assertIn('card', result)
            self.assertEqual(result['card']['title'], 'New Card')
            self.assertIn('created successfully', result['message'])


class TestBasecampClientCardTables(unittest.TestCase):
    """Test BasecampClient card table methods."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = BasecampClient(
            access_token='test_token',
            account_id='12345',
            user_agent='Test Agent',
            auth_mode='oauth'
        )
        
    def test_patch_method_exists(self):
        """Test that patch method exists."""
        self.assertTrue(hasattr(self.client, 'patch'))
        
    @patch('requests.get')
    def test_get_card_table(self, mock_get):
        """Test getting card table from project dock."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'id': '123',
            'dock': [
                {'name': 'todoset', 'id': '111'},
                {'name': 'card_table', 'id': '222'},
                {'name': 'message_board', 'id': '333'}
            ]
        }
        mock_get.return_value = mock_response
        
        result = self.client.get_card_table('123')
        
        self.assertEqual(result['name'], 'card_table')
        self.assertEqual(result['id'], '222')
        
    @patch('requests.post')
    def test_create_column(self, mock_post):
        """Test creating a column."""
        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            'id': '456',
            'title': 'New Column',
            'position': 5
        }
        mock_post.return_value = mock_response
        
        result = self.client.create_column('123', '456', 'New Column')
        
        self.assertEqual(result['title'], 'New Column')
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertEqual(call_args[1]['json'], {'title': 'New Column'})
        
    @patch('requests.patch')
    def test_update_column_color(self, mock_patch):
        """Test updating column color."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            'id': '456',
            'title': 'Column',
            'color': '#FF0000'
        }
        mock_patch.return_value = mock_response
        
        result = self.client.update_column_color('123', '456', '#FF0000')
        
        self.assertEqual(result['color'], '#FF0000')
        mock_patch.assert_called_once()
        call_args = mock_patch.call_args
        self.assertEqual(call_args[1]['json'], {'color': '#FF0000'})


if __name__ == '__main__':
    unittest.main(verbosity=2)