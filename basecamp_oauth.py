"""
Basecamp 3 OAuth 2.0 Authentication Module

This module provides the functionality to authenticate with Basecamp 3
using OAuth 2.0, which is necessary when using Google Authentication (SSO).
"""

import os
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# OAuth 2.0 endpoints for Basecamp - these stay the same for Basecamp 2 and 3
AUTH_URL = "https://launchpad.37signals.com/authorization/new"
TOKEN_URL = "https://launchpad.37signals.com/authorization/token"
IDENTITY_URL = "https://launchpad.37signals.com/authorization.json"

class BasecampOAuth:
    """
    OAuth 2.0 client for Basecamp 3.
    """
    
    def __init__(self, client_id=None, client_secret=None, redirect_uri=None, user_agent=None):
        """Initialize the OAuth client with credentials."""
        self.client_id = client_id or os.getenv('BASECAMP_CLIENT_ID')
        self.client_secret = client_secret or os.getenv('BASECAMP_CLIENT_SECRET')
        self.redirect_uri = redirect_uri or os.getenv('BASECAMP_REDIRECT_URI')
        self.user_agent = user_agent or os.getenv('USER_AGENT')
        
        if not all([self.client_id, self.client_secret, self.redirect_uri, self.user_agent]):
            raise ValueError("Missing required OAuth credentials. Set them in .env file or pass them to the constructor.")
    
    def get_authorization_url(self, state=None):
        """
        Get the URL to redirect the user to for authorization.
        
        Args:
            state (str, optional): A random string to maintain state between requests
            
        Returns:
            str: The authorization URL
        """
        params = {
            'type': 'web_server',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri
        }
        
        if state:
            params['state'] = state
            
        return f"{AUTH_URL}?{urlencode(params)}"
    
    def exchange_code_for_token(self, code):
        """
        Exchange the authorization code for an access token.
        
        Args:
            code (str): The authorization code received after user grants permission
            
        Returns:
            dict: The token response containing access_token and refresh_token
        """
        data = {
            'type': 'web_server',
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'client_secret': self.client_secret,
            'code': code
        }
        
        headers = {
            'User-Agent': self.user_agent
        }
        
        response = requests.post(TOKEN_URL, data=data, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to exchange code for token: {response.status_code} - {response.text}")
    
    def refresh_token(self, refresh_token):
        """
        Refresh an expired access token.
        
        Args:
            refresh_token (str): The refresh token from the original token response
            
        Returns:
            dict: The new token response containing a new access_token
        """
        data = {
            'type': 'refresh',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'refresh_token': refresh_token
        }
        
        headers = {
            'User-Agent': self.user_agent
        }
        
        response = requests.post(TOKEN_URL, data=data, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to refresh token: {response.status_code} - {response.text}")
    
    def get_identity(self, access_token):
        """
        Get the identity and account information for the authenticated user.
        
        Args:
            access_token (str): The OAuth access token
            
        Returns:
            dict: The identity and account information
        """
        headers = {
            'User-Agent': self.user_agent,
            'Authorization': f"Bearer {access_token}"
        }
        
        response = requests.get(IDENTITY_URL, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get identity: {response.status_code} - {response.text}") 