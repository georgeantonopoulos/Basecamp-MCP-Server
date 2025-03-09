"""
Flask application for handling the Basecamp 3 OAuth 2.0 authorization flow.

This application provides endpoints for:
1. Redirecting users to Basecamp for authorization
2. Handling the OAuth callback
3. Using the obtained token to access the Basecamp API
4. Providing a secure token endpoint for the MCP server
"""

import os
import sys
import json
import secrets
import logging
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify
from dotenv import load_dotenv
from basecamp_oauth import BasecampOAuth
from basecamp_client import BasecampClient
from search_utils import BasecampSearch
import token_storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("oauth_app.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Check for required environment variables
required_vars = ['BASECAMP_CLIENT_ID', 'BASECAMP_CLIENT_SECRET', 'BASECAMP_REDIRECT_URI', 'USER_AGENT']
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    logger.error("Please set these variables in your .env file or environment")
    sys.exit(1)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', secrets.token_hex(16))

# HTML template for displaying results
RESULTS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Basecamp 3 OAuth Demo</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        h1 { color: #333; }
        pre { background-color: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto; }
        .button { 
            display: inline-block; 
            background-color: #4CAF50; 
            color: white; 
            padding: 10px 20px; 
            text-decoration: none; 
            border-radius: 5px; 
            margin-top: 20px;
        }
        .container { max-width: 1000px; margin: 0 auto; }
        form { margin-top: 20px; }
        input[type="text"] { padding: 8px; width: 300px; }
        button { padding: 8px 15px; background-color: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="container">
        <h1>{{ title }}</h1>
        {% if message %}
            <p>{{ message }}</p>
        {% endif %}
        {% if content %}
            <pre>{{ content }}</pre>
        {% endif %}
        {% if auth_url %}
            <a href="{{ auth_url }}" class="button">Log in with Basecamp</a>
        {% endif %}
        {% if token_info %}
            <h2>OAuth Token Information</h2>
            <pre>{{ token_info | tojson(indent=2) }}</pre>
        {% endif %}
        {% if show_logout %}
            <a href="/logout" class="button">Logout</a>
        {% endif %}
        {% if show_home %}
            <a href="/" class="button">Home</a>
        {% endif %}
    </div>
</body>
</html>
"""

@app.template_filter('tojson')
def to_json(value, indent=None):
    return json.dumps(value, indent=indent)

def get_oauth_client():
    """Get a configured OAuth client."""
    try:
        client_id = os.getenv('BASECAMP_CLIENT_ID')
        client_secret = os.getenv('BASECAMP_CLIENT_SECRET')
        redirect_uri = os.getenv('BASECAMP_REDIRECT_URI')
        user_agent = os.getenv('USER_AGENT')
        
        logger.info("Creating OAuth client with config: %s, %s, %s", client_id, redirect_uri, user_agent)
        
        return BasecampOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            user_agent=user_agent
        )
    except Exception as e:
        logger.error("Error creating OAuth client: %s", str(e))
        raise

@app.route('/')
def home():
    """Home page."""
    # Check if we have a stored token
    token_data = token_storage.get_token()
    
    if token_data and token_data.get('access_token'):
        # We have a token, show token information
        access_token = token_data['access_token']
        # Mask the token for security
        masked_token = f"{access_token[:10]}...{access_token[-10:]}" if len(access_token) > 20 else "***"
        
        token_info = {
            "access_token": masked_token,
            "account_id": token_data.get('account_id'),
            "has_refresh_token": bool(token_data.get('refresh_token')),
            "expires_at": token_data.get('expires_at'),
            "updated_at": token_data.get('updated_at')
        }
        
        logger.info("Home page: User is authenticated")
        
        return render_template_string(
            RESULTS_TEMPLATE,
            title="Basecamp OAuth Status",
            message="You are authenticated with Basecamp!",
            token_info=token_info,
            show_logout=True
        )
    else:
        # No token, show login button
        try:
            oauth_client = get_oauth_client()
            auth_url = oauth_client.get_authorization_url()
            
            logger.info("Home page: User not authenticated, showing login button")
            
            return render_template_string(
                RESULTS_TEMPLATE,
                title="Basecamp OAuth Demo",
                message="Welcome! Please log in with your Basecamp account to continue.",
                auth_url=auth_url
            )
        except Exception as e:
            logger.error("Error getting authorization URL: %s", str(e))
            return render_template_string(
                RESULTS_TEMPLATE,
                title="Error",
                message=f"Error setting up OAuth: {str(e)}",
            )

@app.route('/auth/callback')
def auth_callback():
    """Handle the OAuth callback from Basecamp."""
    logger.info("OAuth callback called with args: %s", request.args)
    
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        logger.error("OAuth callback error: %s", error)
        return render_template_string(
            RESULTS_TEMPLATE,
            title="Authentication Error",
            message=f"Basecamp returned an error: {error}",
            show_home=True
        )
    
    if not code:
        logger.error("OAuth callback: No code provided")
        return render_template_string(
            RESULTS_TEMPLATE,
            title="Error",
            message="No authorization code received.",
            show_home=True
        )
    
    try:
        # Exchange the code for an access token
        oauth_client = get_oauth_client()
        logger.info("Exchanging code for token")
        token_data = oauth_client.exchange_code_for_token(code)
        
        # Store the token in our secure storage
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token')
        expires_in = token_data.get('expires_in')
        account_id = os.getenv('BASECAMP_ACCOUNT_ID')
        
        if not access_token:
            logger.error("OAuth exchange: No access token received")
            return render_template_string(
                RESULTS_TEMPLATE,
                title="Authentication Error",
                message="No access token received from Basecamp.",
                show_home=True
            )
        
        # Try to get identity if account_id is not set
        if not account_id:
            try:
                logger.info("Getting user identity to find account_id")
                identity = oauth_client.get_identity(access_token)
                logger.info("Identity response: %s", identity)
                
                # Find Basecamp 3 account
                if identity.get('accounts'):
                    for account in identity['accounts']:
                        if account.get('product') == 'bc3':  # Basecamp 3
                            account_id = account['id']
                            logger.info("Found account_id: %s", account_id)
                            break
            except Exception as identity_error:
                logger.error("Error getting identity: %s", str(identity_error))
                # Continue with the flow, but log the error
        
        logger.info("Storing token with account_id: %s", account_id)
        stored = token_storage.store_token(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            account_id=account_id
        )
        
        if not stored:
            logger.error("Failed to store token")
            return render_template_string(
                RESULTS_TEMPLATE,
                title="Error",
                message="Failed to store token. Please try again.",
                show_home=True
            )
        
        # Also keep the access token in session for convenience
        session['access_token'] = access_token
        if refresh_token:
            session['refresh_token'] = refresh_token
        if account_id:
            session['account_id'] = account_id
        
        logger.info("OAuth flow completed successfully")
        
        return redirect(url_for('home'))
    except Exception as e:
        logger.error("Error in OAuth callback: %s", str(e), exc_info=True)
        return render_template_string(
            RESULTS_TEMPLATE,
            title="Error",
            message=f"Failed to exchange code for token: {str(e)}",
            show_home=True
        )

@app.route('/api/token', methods=['GET'])
def get_token_api():
    """
    Secure API endpoint for the MCP server to get the token.
    This should only be accessible by the MCP server.
    """
    logger.info("Token API called with headers: %s", request.headers)
    
    # In production, implement proper authentication for this endpoint
    # For now, we'll use a simple API key check
    api_key = request.headers.get('X-API-Key')
    if not api_key or api_key != os.getenv('MCP_API_KEY', 'mcp_secret_key'):
        logger.error("Token API: Invalid API key")
        return jsonify({
            "error": "Unauthorized",
            "message": "Invalid or missing API key"
        }), 401
    
    token_data = token_storage.get_token()
    if not token_data or not token_data.get('access_token'):
        logger.error("Token API: No valid token available")
        return jsonify({
            "error": "Not authenticated",
            "message": "No valid token available"
        }), 404
    
    logger.info("Token API: Successfully returned token")
    return jsonify({
        "access_token": token_data['access_token'],
        "account_id": token_data.get('account_id')
    })

@app.route('/logout')
def logout():
    """Clear the session and token storage."""
    logger.info("Logout called")
    session.clear()
    token_storage.clear_tokens()
    return redirect(url_for('home'))

@app.route('/token/info')
def token_info():
    """Display information about the stored token."""
    logger.info("Token info called")
    token_data = token_storage.get_token()
    
    if not token_data:
        logger.info("Token info: No token stored")
        return render_template_string(
            RESULTS_TEMPLATE,
            title="Token Information",
            message="No token stored.",
            show_home=True
        )
    
    # Mask the tokens for security
    access_token = token_data.get('access_token', '')
    refresh_token = token_data.get('refresh_token', '')
    
    masked_access = f"{access_token[:10]}...{access_token[-10:]}" if len(access_token) > 20 else "***"
    masked_refresh = f"{refresh_token[:10]}...{refresh_token[-10:]}" if refresh_token and len(refresh_token) > 20 else "***" if refresh_token else None
    
    display_info = {
        "access_token": masked_access,
        "has_refresh_token": bool(refresh_token),
        "account_id": token_data.get('account_id'),
        "expires_at": token_data.get('expires_at'),
        "updated_at": token_data.get('updated_at')
    }
    
    logger.info("Token info: Returned token info")
    return render_template_string(
        RESULTS_TEMPLATE,
        title="Token Information",
        content=json.dumps(display_info, indent=2),
        show_home=True
    )

@app.route('/health')
def health_check():
    """Health check endpoint."""
    logger.info("Health check called")
    return jsonify({
        "status": "ok",
        "service": "basecamp-oauth-app"
    })

if __name__ == '__main__':
    try:
        logger.info("Starting OAuth app on port %s", os.environ.get('PORT', 8000))
        # Run the Flask app
        port = int(os.environ.get('PORT', 8000))
        
        # Disable debug and auto-reloader when running in production or background
        is_debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
        
        logger.info("Running in %s mode", "debug" if is_debug else "production")
        app.run(host='0.0.0.0', port=port, debug=is_debug, use_reloader=is_debug)
    except Exception as e:
        logger.error("Fatal error: %s", str(e), exc_info=True)
        sys.exit(1) 