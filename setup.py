#!/usr/bin/env python3
"""
Complete setup script for Basecamp MCP Integration.
This script handles the entire setup process for new users.
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

def run_command(cmd, cwd=None):
    """Run a command and return success status."""
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Command failed: {cmd}")
            print(f"Error: {result.stderr}")
            return False
        return True
    except Exception as e:
        print(f"❌ Error running command '{cmd}': {str(e)}")
        return False

def check_python_version():
    """Check if Python version is 3.10+"""
    if sys.version_info < (3, 10):
        print("❌ Python 3.10 or higher is required (for MCP SDK compatibility)")
        print(f"Current version: {sys.version}")
        print("\n💡 Tip: Use 'uv' to auto-download the correct Python version:")
        print("   uv venv --python 3.12 venv")
        print("   source venv/bin/activate")
        print("   uv pip install -r requirements.txt && uv pip install mcp")
        return False
    print(f"✅ Python version: {sys.version.split()[0]}")
    return True

def create_venv():
    """Create virtual environment."""
    print("📦 Creating virtual environment...")
    if os.path.exists("venv"):
        print("⚠️  Virtual environment already exists, skipping creation")
        return True
    
    if not run_command(f"{sys.executable} -m venv venv"):
        return False
    print("✅ Virtual environment created")
    return True

def get_venv_python():
    """Get the path to the virtual environment Python."""
    if platform.system() == "Windows":
        return "venv\\Scripts\\python.exe"
    else:
        return "venv/bin/python"

def install_dependencies():
    """Install dependencies in the virtual environment."""
    print("📚 Installing dependencies...")
    venv_python = get_venv_python()
    
    # Upgrade pip first
    if not run_command(f"{venv_python} -m pip install --upgrade pip"):
        return False
    
    # Install requirements
    if not run_command(f"{venv_python} -m pip install -r requirements.txt"):
        return False
    
    print("✅ Dependencies installed")
    return True

def create_env_template():
    """Create .env template file if it doesn't exist."""
    env_path = ".env"
    if os.path.exists(env_path):
        print("⚠️  .env file already exists, skipping template creation")
        return True
    
    print("📝 Creating .env template...")
    template = """# Basecamp OAuth Configuration
BASECAMP_CLIENT_ID=your_client_id_here
BASECAMP_CLIENT_SECRET=your_client_secret_here
BASECAMP_REDIRECT_URI=http://localhost:8000/auth/callback
BASECAMP_ACCOUNT_ID=your_account_id_here
USER_AGENT="Your App Name (your@email.com)"
FLASK_SECRET_KEY=auto_generated_secret_key
MCP_API_KEY=auto_generated_mcp_key
"""
    
    try:
        with open(env_path, 'w') as f:
            f.write(template)
        print("✅ .env template created")
        return True
    except Exception as e:
        print(f"❌ Failed to create .env template: {str(e)}")
        return False

def check_env_file():
    """Check if .env file is properly configured."""
    env_path = ".env"
    if not os.path.exists(env_path):
        print("❌ .env file not found")
        return False
    
    required_vars = [
        'BASECAMP_CLIENT_ID',
        'BASECAMP_CLIENT_SECRET', 
        'BASECAMP_ACCOUNT_ID',
        'USER_AGENT'
    ]
    
    try:
        with open(env_path, 'r') as f:
            content = f.read()
        
        missing_vars = []
        for var in required_vars:
            if f"{var}=your_" in content or f"{var}=" not in content:
                missing_vars.append(var)
        
        if missing_vars:
            print("⚠️  Please configure these variables in .env:")
            for var in missing_vars:
                print(f"   - {var}")
            return False
        
        print("✅ .env file configured")
        return True
    except Exception as e:
        print(f"❌ Error reading .env file: {str(e)}")
        return False

def test_mcp_server():
    """Test if the MCP server can start."""
    print("🧪 Testing MCP server...")
    venv_python = get_venv_python()
    
    # Test import
    test_cmd = f'{venv_python} -c "import mcp; print(\\"MCP available\\")"'
    if not run_command(test_cmd):
        print("❌ MCP package not available")
        return False
    
    print("✅ MCP server test passed")
    return True

def main():
    """Main setup function."""
    print("🚀 Basecamp MCP Integration Setup")
    print("=" * 40)
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Create virtual environment
    if not create_venv():
        return False
    
    # Install dependencies
    if not install_dependencies():
        return False
    
    # Create .env template
    if not create_env_template():
        return False
    
    # Test MCP server
    if not test_mcp_server():
        return False
    
    print("\n" + "=" * 40)
    print("✅ Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Edit .env file with your Basecamp OAuth credentials")
    print("2. Run: python oauth_app.py (to authenticate)")
    print("3. Run: python generate_cursor_config.py (to configure Cursor)")
    print("4. Restart Cursor completely")
    print("\n💡 Need OAuth credentials? Create an app at:")
    print("   https://launchpad.37signals.com/integrations")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 