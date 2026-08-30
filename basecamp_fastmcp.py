#!/usr/bin/env python3
"""
FastMCP server for Basecamp integration.

This server implements the MCP (Model Context Protocol) using the official
Anthropic FastMCP framework, replacing the custom JSON-RPC implementation.
"""

import base64
import functools
import json
import logging
import os
import sys
from typing import Any, Dict, List, Literal, Optional
import anyio
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import (
    BlobResourceContents,
    EmbeddedResource,
    ImageContent,
    TextContent,
)

# Import existing business logic
from basecamp_client import BasecampClient
from search_utils import BasecampSearch
from recording_utils import compact_recording
import token_storage
import auth_manager
from dotenv import load_dotenv

# Determine project root (directory containing this script)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(DOTENV_PATH)

# Set up logging to file AND stderr (following MCP best practices)
LOG_FILE_PATH = os.path.join(PROJECT_ROOT, 'basecamp_fastmcp.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler(sys.stderr)  # Critical: log to stderr, not stdout
    ]
)
logger = logging.getLogger('basecamp_fastmcp')

# Initialize FastMCP server
mcp = FastMCP("basecamp")

# Auth helper functions (reused from original server)
def _get_basecamp_client() -> Optional[BasecampClient]:
    """Get authenticated Basecamp client (sync version from original server)."""
    try:
        token_data = token_storage.get_token()
        logger.debug(
            "Token data retrieved: has_access_token=%s has_refresh_token=%s account_id=%s expires_at=%s",
            bool(token_data and token_data.get('access_token')),
            bool(token_data and token_data.get('refresh_token')),
            token_data.get('account_id') if token_data else None,
            token_data.get('expires_at') if token_data else None,
        )

        if not token_data or not token_data.get('access_token'):
            logger.error("No OAuth token available")
            return None

        # Check and automatically refresh if token is expired
        if not auth_manager.ensure_authenticated():
            logger.error("OAuth token has expired and automatic refresh failed")
            return None

        # Get fresh token data after potential refresh
        token_data = token_storage.get_token()

        # Get account_id from token data first, then fall back to env var
        account_id = token_data.get('account_id') or os.getenv('BASECAMP_ACCOUNT_ID')
        user_agent = os.getenv('USER_AGENT')

        if not account_id:
            logger.error(
                "Missing account_id. token_account_id=%s env_BASECAMP_ACCOUNT_ID=%s",
                token_data.get('account_id') if token_data else None,
                os.getenv('BASECAMP_ACCOUNT_ID'),
            )
            return None
        if not user_agent:
            logger.error("Missing USER_AGENT; refusing to create Basecamp client")
            return None

        logger.debug(f"Creating Basecamp client with account_id: {account_id}, user_agent: {user_agent}")

        return BasecampClient(
            access_token=token_data['access_token'],
            account_id=account_id,
            user_agent=user_agent,
            auth_mode='oauth'
        )
    except Exception as e:
        logger.error(f"Error creating Basecamp client: {e}")
        return None

def _error_response(error: str, message: str) -> Dict[str, Any]:
    """Return a consistent MCP tool error response."""
    return {
        "status": "error",
        "error": error,
        "message": message,
    }


def _get_auth_error_response() -> Dict[str, Any]:
    """Return consistent auth error response."""
    if not os.getenv("USER_AGENT"):
        return _error_response(
            "Configuration required",
            "Set USER_AGENT in .env to a descriptive app name with a contact email before using Basecamp.",
        )
    if token_storage.is_token_expired():
        return _error_response(
            "OAuth token expired",
            "Your Basecamp OAuth token has expired. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
        )
    return _error_response(
        "Authentication required",
        "Please authenticate with Basecamp first. Visit http://localhost:8000 to log in.",
    )

async def _run_sync(func, *args, **kwargs):
    """Wrapper to run synchronous functions in thread pool."""
    if kwargs:
        func = functools.partial(func, **kwargs)
    return await anyio.to_thread.run_sync(func, *args)


def _handle_download_error(e: Exception, kind: str) -> Dict[str, Any]:
    """Map a BasecampClient download exception to an MCP error response."""
    logger.error(f"Error downloading {kind}: {e}")
    if "401" in str(e) and "expired" in str(e).lower():
        return _error_response(
            "OAuth token expired",
            "Your Basecamp OAuth token expired during the API call. Re-authenticate via this server's OAuth endpoint.",
        )
    return _error_response("Execution error", str(e))


def _serialize_blob_for_mcp(
    data: bytes,
    content_type: str,
    filename: str,
    summary: str,
    resource_uri: str,
) -> List[Any]:
    """Pack a downloaded file into MCP content blocks.

    ``image/*`` MIME types come back as ``ImageContent`` (the MCP host can
    render them); everything else as an ``EmbeddedResource`` with
    ``BlobResourceContents`` so the MCP host forwards the bytes to the model
    and PDFs/docs are read natively.
    """
    b64 = base64.b64encode(data).decode("ascii")
    blocks: List[Any] = [TextContent(type="text", text=summary)]
    if content_type.startswith("image/"):
        blocks.append(
            ImageContent(type="image", data=b64, mimeType=content_type)
        )
    else:
        blocks.append(
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(
                    uri=resource_uri,
                    mimeType=content_type,
                    blob=b64,
                ),
            )
        )
    return blocks


# Core MCP Tools - Starting with essential ones from original server

@mcp.tool()
async def get_projects() -> Dict[str, Any]:
    """Get all Basecamp projects."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        projects = await _run_sync(client.get_projects)
        return {
            "status": "success",
            "projects": projects,
            "count": len(projects)
        }
    except Exception as e:
        logger.error(f"Error getting projects: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_project(name: str, description: Optional[str] = None, admissions: Optional[str] = None) -> Dict[str, Any]:
    """Create a Basecamp project."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        project = await _run_sync(client.create_project, name, description, admissions)
        return {"status": "success", "project": project, "message": "Project created successfully"}
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_project(
    project_id: str,
    name: str,
    description: Optional[str] = None,
    admissions: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a project's name, description, access policy, or date range."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        project = await _run_sync(
            client.update_project,
            project_id,
            name,
            description,
            admissions,
            start_date,
            end_date,
        )
        return {"status": "success", "project": project, "message": "Project updated successfully"}
    except Exception as e:
        logger.error(f"Error updating project {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def trash_project(project_id: str) -> Dict[str, Any]:
    """Move a Basecamp project to the trash."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.trash_project, project_id)
        return {"status": "success", "message": "Project trashed successfully"}
    except Exception as e:
        logger.error(f"Error trashing project {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_dock_tool(tool_id: str) -> Dict[str, Any]:
    """Get one Basecamp project dock tool."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        tool = await _run_sync(client.get_dock_tool, tool_id)
        return {"status": "success", "tool": tool}
    except Exception as e:
        logger.error(f"Error getting dock tool {tool_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_dock_tool(
    project_id: str,
    tool_type: str,
    title: Optional[str] = None,
    visible_to_clients: Optional[bool] = None,
) -> Dict[str, Any]:
    """Add a tool to a Basecamp project's dock."""
    valid_types = {
        "Message::Board", "Todoset", "Vault", "Schedule", "Chat::Transcript",
        "Kanban::Board", "Questionnaire", "Inbox",
    }
    if tool_type not in valid_types:
        return _error_response("Invalid input", "unsupported dock tool type")
    if visible_to_clients is not None and not isinstance(visible_to_clients, bool):
        return _error_response("Invalid input", "visible_to_clients must be a boolean")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        tool = await _run_sync(
            client.create_dock_tool,
            project_id,
            tool_type,
            title,
            visible_to_clients,
        )
        return {"status": "success", "tool": tool, "message": "Dock tool created"}
    except Exception as e:
        logger.error(f"Error creating dock tool for {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_dock_tool(tool_id: str, title: str) -> Dict[str, Any]:
    """Rename a Basecamp project dock tool."""
    if not title or not title.strip():
        return _error_response("Invalid input", "title is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        tool = await _run_sync(client.update_dock_tool, tool_id, title)
        return {"status": "success", "tool": tool, "message": "Dock tool renamed"}
    except Exception as e:
        logger.error(f"Error updating dock tool {tool_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def enable_dock_tool(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Enable a recording in a Basecamp project's dock."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.enable_dock_tool, project_id, recording_id)
        return {"status": "success", "message": "Dock tool enabled"}
    except Exception as e:
        logger.error(f"Error enabling dock tool {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def reposition_dock_tool(
    project_id: str, recording_id: str, position: int
) -> Dict[str, Any]:
    """Move a Basecamp project dock tool to a one-based position."""
    if isinstance(position, bool) or not isinstance(position, int) or position < 1:
        return _error_response("Invalid input", "position must be a positive integer")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.reposition_dock_tool, project_id, recording_id, position)
        return {"status": "success", "message": "Dock tool repositioned"}
    except Exception as e:
        logger.error(f"Error repositioning dock tool {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def disable_dock_tool(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Hide a recording from a Basecamp project's dock without deleting it."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.disable_dock_tool, project_id, recording_id)
        return {"status": "success", "message": "Dock tool disabled"}
    except Exception as e:
        logger.error(f"Error disabling dock tool {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def trash_dock_tool(tool_id: str) -> Dict[str, Any]:
    """Permanently delete a Basecamp dock tool and its content."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.trash_dock_tool, tool_id)
        return {"status": "success", "message": "Dock tool permanently deleted"}
    except Exception as e:
        logger.error(f"Error trashing dock tool {tool_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_templates(status: str = "active") -> Dict[str, Any]:
    """List visible Basecamp project templates."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        templates = await _run_sync(client.get_templates, status)
        return {"status": "success", "templates": templates, "count": len(templates)}
    except Exception as e:
        logger.error(f"Error getting templates: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_template(template_id: str) -> Dict[str, Any]:
    """Get a Basecamp project template."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        template = await _run_sync(client.get_template, template_id)
        return {"status": "success", "template": template}
    except Exception as e:
        logger.error(f"Error getting template {template_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_template(name: str, description: Optional[str] = None) -> Dict[str, Any]:
    """Create a Basecamp project template."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        template = await _run_sync(client.create_template, name, description)
        return {"status": "success", "template": template, "message": "Template created successfully"}
    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_template(
    template_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Update a Basecamp project template."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        template = await _run_sync(client.update_template, template_id, name, description)
        return {"status": "success", "template": template, "message": "Template updated successfully"}
    except Exception as e:
        logger.error(f"Error updating template {template_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def trash_template(template_id: str) -> Dict[str, Any]:
    """Move a Basecamp project template to the trash."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.trash_template, template_id)
        return {"status": "success", "message": "Template trashed successfully"}
    except Exception as e:
        logger.error(f"Error trashing template {template_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_project_from_template(
    template_id: str,
    project_name: str,
    project_description: Optional[str] = None,
) -> Dict[str, Any]:
    """Start constructing a project from a Basecamp template."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        construction = await _run_sync(
            client.create_project_from_template,
            template_id,
            project_name,
            project_description,
        )
        return {"status": "success", "construction": construction}
    except Exception as e:
        logger.error(f"Error constructing project from template {template_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_project_construction(template_id: str, construction_id: str) -> Dict[str, Any]:
    """Get the status of a project being constructed from a template."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        construction = await _run_sync(client.get_project_construction, template_id, construction_id)
        return {"status": "success", "construction": construction}
    except Exception as e:
        logger.error(f"Error getting project construction {construction_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_people() -> Dict[str, Any]:
    """Get people available in the authenticated Basecamp account."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        people = await _run_sync(client.get_people)
        return {
            "status": "success",
            "people": people,
            "count": len(people),
        }
    except Exception as e:
        logger.error(f"Error getting people: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {
            "error": "Execution error",
            "message": str(e),
        }

@mcp.tool()
async def get_project_people(project_id: str) -> Dict[str, Any]:
    """Get active people on a Basecamp project."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        people = await _run_sync(client.get_project_people, project_id)
        return {"status": "success", "people": people, "count": len(people)}
    except Exception as e:
        logger.error(f"Error getting people for project {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_project_people(
    project_id: str,
    grant: Optional[List[str]] = None,
    revoke: Optional[List[str]] = None,
    create: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Grant, revoke, or invite people on a Basecamp project."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        result = await _run_sync(client.update_project_people, project_id, grant, revoke, create)
        return {"status": "success", "result": result, "message": "Project access updated successfully"}
    except Exception as e:
        logger.error(f"Error updating people for project {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_pingable_people() -> Dict[str, Any]:
    """Get Basecamp people who can be pinged."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        people = await _run_sync(client.get_pingable_people)
        return {"status": "success", "people": people, "count": len(people)}
    except Exception as e:
        logger.error(f"Error getting pingable people: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_person(person_id: str) -> Dict[str, Any]:
    """Get one Basecamp person's profile."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        person = await _run_sync(client.get_person, person_id)
        return {"status": "success", "person": person}
    except Exception as e:
        logger.error(f"Error getting person {person_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_my_profile() -> Dict[str, Any]:
    """Get the authenticated person's Basecamp profile."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        person = await _run_sync(client.get_my_profile)
        return {"status": "success", "person": person}
    except Exception as e:
        logger.error(f"Error getting current profile: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_my_assignments() -> Dict[str, Any]:
    """Get the authenticated user's active assignments grouped by priority."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        assignments = await _run_sync(client.get_my_assignments)
        return {"status": "success", "assignments": assignments}
    except Exception as e:
        logger.error(f"Error getting assignments: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_completed_assignments() -> Dict[str, Any]:
    """Get the authenticated user's completed assignments."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        assignments = await _run_sync(client.get_completed_assignments)
        return {"status": "success", "assignments": assignments, "count": len(assignments)}
    except Exception as e:
        logger.error(f"Error getting completed assignments: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_due_assignments(scope: str = "overdue") -> Dict[str, Any]:
    """Get the authenticated user's assignments by due-date scope."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        assignments = await _run_sync(client.get_due_assignments, scope)
        return {"status": "success", "assignments": assignments, "count": len(assignments)}
    except Exception as e:
        logger.error(f"Error getting due assignments: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_assignable_people() -> Dict[str, Any]:
    """Get the account-wide list of people who can receive to-do assignments."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        people = await _run_sync(client.get_assignable_people)
        return {"status": "success", "people": people, "count": len(people)}
    except Exception as exc:
        logger.error("Error getting assignable people: %s", exc)
        return _error_response("Execution error", str(exc))


@mcp.tool()
async def get_person_assignments(
    person_id: str,
    group_by: Optional[Literal["bucket", "date"]] = None,
) -> Dict[str, Any]:
    """Get one person's active to-do assignments across all projects."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        report = await _run_sync(client.get_person_assignments, person_id, group_by)
        todos = report.get("todos") or []
        return {
            "status": "success",
            "person": report.get("person"),
            "grouped_by": report.get("grouped_by"),
            "todos": todos,
            "count": len(todos),
        }
    except Exception as exc:
        logger.error("Error getting assignments for person %s: %s", person_id, exc)
        return _error_response("Execution error", str(exc))


@mcp.tool()
async def get_overdue_todos() -> Dict[str, Any]:
    """Get overdue to-dos across all accessible projects."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        overdue = await _run_sync(client.get_overdue_todos)
        return {"status": "success", "overdue": overdue}
    except Exception as e:
        logger.error(f"Error getting overdue todos: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_upcoming_schedule(window_starts_on: str, window_ends_on: str) -> Dict[str, Any]:
    """Get upcoming events and due work across all accessible projects."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        upcoming = await _run_sync(
            client.get_upcoming_schedule,
            window_starts_on,
            window_ends_on,
        )
        return {"status": "success", "upcoming": upcoming}
    except Exception as e:
        logger.error(f"Error getting upcoming schedule: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_account() -> Dict[str, Any]:
    """Get the Basecamp account associated with the current access token."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        account = await _run_sync(client.get_account)
        return {"status": "success", "account": account}
    except Exception as e:
        logger.error(f"Error getting account: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_account_name(name: str) -> Dict[str, Any]:
    """Rename the current Basecamp account (owner only)."""
    if not name or not name.strip():
        return _error_response("Invalid input", "name is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        account = await _run_sync(client.update_account_name, name)
        return {"status": "success", "account": account, "message": "Account renamed"}
    except Exception as e:
        logger.error(f"Error updating account name: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_account_logo(file_path: str) -> Dict[str, Any]:
    """Upload or replace the account logo (administrator/owner only)."""
    if not file_path:
        return _error_response("Invalid input", "file_path is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.update_account_logo, file_path)
        return {"status": "success", "message": "Account logo updated"}
    except Exception as e:
        logger.error(f"Error updating account logo: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def remove_account_logo() -> Dict[str, Any]:
    """Remove the account logo (administrator/owner only)."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.remove_account_logo)
        return {"status": "success", "message": "Account logo removed"}
    except Exception as e:
        logger.error(f"Error removing account logo: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_everything_messages(limit: Optional[int] = 100, page: Optional[int] = None) -> Dict[str, Any]:
    """Get recent messages across every accessible Basecamp project."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        messages = await _run_sync(client.get_everything_messages, limit, page)
        return {"status": "success", "messages": messages, "count": len(messages)}
    except Exception as e:
        logger.error(f"Error getting account-wide messages: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_everything_comments(limit: Optional[int] = 100, page: Optional[int] = None) -> Dict[str, Any]:
    """Get recent comments across every accessible Basecamp project."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        comments = await _run_sync(client.get_everything_comments, limit, page)
        return {"status": "success", "comments": comments, "count": len(comments)}
    except Exception as e:
        logger.error(f"Error getting account-wide comments: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_everything_checkins(limit: Optional[int] = 100, page: Optional[int] = None) -> Dict[str, Any]:
    """Get automatic check-in answers across every accessible project."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        checkins = await _run_sync(client.get_everything_checkins, limit, page)
        return {"status": "success", "checkins": checkins, "count": len(checkins)}
    except Exception as e:
        logger.error(f"Error getting account-wide check-ins: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_everything_forwards(limit: Optional[int] = 100, page: Optional[int] = None) -> Dict[str, Any]:
    """Get inbox forwards across every accessible Basecamp project."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        forwards = await _run_sync(client.get_everything_forwards, limit, page)
        return {"status": "success", "forwards": forwards, "count": len(forwards)}
    except Exception as e:
        logger.error(f"Error getting account-wide forwards: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_everything_files(
    limit: Optional[int] = 100,
    kind: str = "all",
    person_ids: Optional[List[str]] = None,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    """Get files across every accessible project, optionally filtered by kind or creator."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    if kind not in {"all", "images", "pdfs", "documents", "videos"}:
        return _error_response("Invalid input", "kind must be one of: all, images, pdfs, documents, videos")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        files = await _run_sync(client.get_everything_files, limit, kind, person_ids, page)
        return {"status": "success", "files": files, "count": len(files)}
    except Exception as e:
        logger.error(f"Error getting account-wide files: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_everything_todos(
    status: str = "open",
    limit: Optional[int] = 100,
    assignee_ids: Optional[List[str]] = None,
    due: Optional[str] = None,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    """Get filtered to-dos grouped by project across the whole account."""
    valid_statuses = {"open", "completed", "unassigned", "no_due_date", "overdue"}
    if status not in valid_statuses:
        return _error_response("Invalid input", f"status must be one of: {', '.join(sorted(valid_statuses))}")
    if due is not None and due not in {"with", "without", "overdue"}:
        return _error_response("Invalid input", "due must be one of: with, without, overdue")
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        todos = await _run_sync(client.get_everything_todos, status, limit, assignee_ids, due, page)
        return {"status": "success", "todos": todos, "count": len(todos), "filter": status}
    except Exception as e:
        logger.error(f"Error getting account-wide todos: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_everything_cards(
    status: str = "open",
    limit: Optional[int] = 100,
    assignee_ids: Optional[List[str]] = None,
    due: Optional[str] = None,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    """Get filtered cards grouped by project across the whole account."""
    valid_statuses = {"open", "completed", "unassigned", "no_due_date", "not_now", "overdue"}
    if status not in valid_statuses:
        return _error_response("Invalid input", f"status must be one of: {', '.join(sorted(valid_statuses))}")
    if due is not None and due not in {"with", "without", "overdue"}:
        return _error_response("Invalid input", "due must be one of: with, without, overdue")
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        cards = await _run_sync(client.get_everything_cards, status, limit, assignee_ids, due, page)
        return {"status": "success", "cards": cards, "count": len(cards), "filter": status}
    except Exception as e:
        logger.error(f"Error getting account-wide cards: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_timeline(limit: Optional[int] = 100, page: Optional[int] = None) -> Dict[str, Any]:
    """Get recent activity across every accessible Basecamp project."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        events = await _run_sync(client.get_timeline, limit, page)
        return {"status": "success", "events": events, "count": len(events)}
    except Exception as e:
        logger.error(f"Error getting account timeline: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_project_timeline(project_id: str, limit: Optional[int] = 100, page: Optional[int] = None) -> Dict[str, Any]:
    """Get recent activity within one Basecamp project."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        events = await _run_sync(client.get_project_timeline, project_id, limit, page)
        return {"status": "success", "events": events, "count": len(events)}
    except Exception as e:
        logger.error(f"Error getting project timeline for {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_person_timeline(person_id: str, limit: Optional[int] = 100, page: Optional[int] = None) -> Dict[str, Any]:
    """Get timeline activity created by one Basecamp person."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        timeline = await _run_sync(client.get_person_timeline, person_id, limit, page)
        return {"status": "success", "timeline": timeline, "count": len(timeline.get("events", []))}
    except Exception as e:
        logger.error(f"Error getting timeline for person {person_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_hill_chart(todoset_id: str) -> Dict[str, Any]:
    """Get the Basecamp Hill Chart for a to-do set."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        hill_chart = await _run_sync(client.get_hill_chart, todoset_id)
        return {"status": "success", "hill_chart": hill_chart}
    except Exception as e:
        logger.error(f"Error getting Hill Chart for todoset {todoset_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_project_hill_chart(project_id: str) -> Dict[str, Any]:
    """Resolve and get a project's Basecamp Hill Chart."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        hill_chart = await _run_sync(client.get_project_hill_chart, project_id)
        return {"status": "success", "hill_chart": hill_chart}
    except Exception as e:
        logger.error(f"Error getting Hill Chart for project {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_hill_chart_settings(
    todoset_id: str,
    tracked: Optional[List[str]] = None,
    untracked: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Track or untrack to-do lists on a Basecamp Hill Chart."""
    if not tracked and not untracked:
        return _error_response("Invalid input", "tracked or untracked is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        hill_chart = await _run_sync(
            client.update_hill_chart_settings, todoset_id, tracked, untracked
        )
        return {"status": "success", "hill_chart": hill_chart}
    except Exception as e:
        logger.error(f"Error updating Hill Chart for todoset {todoset_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_timesheet_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    person_id: Optional[str] = None,
    bucket_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get the account-wide, non-paginated Basecamp timesheet report."""
    if (start_date is None) != (end_date is None):
        return _error_response(
            "Invalid input", "start_date and end_date must be provided together"
        )
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        entries = await _run_sync(
            client.get_timesheet_report, start_date, end_date, person_id, bucket_id
        )
        return {"status": "success", "entries": entries, "count": len(entries)}
    except Exception as e:
        logger.error(f"Error getting timesheet report: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_project_timesheet(
    project_id: str, limit: Optional[int] = 100, page: Optional[int] = None
) -> Dict[str, Any]:
    """Get paginated timesheet entries for a Basecamp project."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        entries = await _run_sync(client.get_project_timesheet, project_id, limit, page)
        return {"status": "success", "entries": entries, "count": len(entries)}
    except Exception as e:
        logger.error(f"Error getting project timesheet for {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_recording_timesheet(
    recording_id: str, limit: Optional[int] = 100, page: Optional[int] = None
) -> Dict[str, Any]:
    """Get paginated timesheet entries for a Basecamp recording."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        entries = await _run_sync(
            client.get_recording_timesheet, recording_id, limit, page
        )
        return {"status": "success", "entries": entries, "count": len(entries)}
    except Exception as e:
        logger.error(f"Error getting recording timesheet for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_timesheet_entry(entry_id: str) -> Dict[str, Any]:
    """Get one Basecamp timesheet entry."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        entry = await _run_sync(client.get_timesheet_entry, entry_id)
        return {"status": "success", "entry": entry}
    except Exception as e:
        logger.error(f"Error getting timesheet entry {entry_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_timesheet_entry(
    recording_id: str,
    date: str,
    hours: str,
    description: Optional[str] = None,
    person_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Log time against a Basecamp timesheetable recording."""
    if not date:
        return _error_response("Invalid input", "date is required")
    if not hours:
        return _error_response("Invalid input", "hours is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        entry = await _run_sync(
            client.create_timesheet_entry,
            recording_id,
            date,
            hours,
            description,
            person_id,
        )
        return {"status": "success", "entry": entry, "message": "Timesheet entry created"}
    except Exception as e:
        logger.error(f"Error creating timesheet entry for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_timesheet_entry(
    entry_id: str,
    date: Optional[str] = None,
    hours: Optional[str] = None,
    description: Optional[str] = None,
    person_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Update selected fields on a Basecamp timesheet entry."""
    if date is None and hours is None and description is None and person_id is None:
        return _error_response(
            "Invalid input", "at least one timesheet field is required"
        )
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        entry = await _run_sync(
            client.update_timesheet_entry,
            entry_id,
            date,
            hours,
            description,
            person_id,
        )
        return {"status": "success", "entry": entry, "message": "Timesheet entry updated"}
    except Exception as e:
        logger.error(f"Error updating timesheet entry {entry_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def delete_timesheet_entry(entry_id: str) -> Dict[str, Any]:
    """Permanently delete a Basecamp timesheet entry."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.delete_timesheet_entry, entry_id)
        return {"status": "success", "message": "Timesheet entry deleted"}
    except Exception as e:
        logger.error(f"Error deleting timesheet entry {entry_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_gauges(
    bucket_ids: Optional[List[str]] = None,
    limit: Optional[int] = 100,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    """List project gauges across the authenticated Basecamp account."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        gauges = await _run_sync(client.get_gauges, bucket_ids, limit, page)
        return {"status": "success", "gauges": gauges, "count": len(gauges)}
    except Exception as e:
        logger.error(f"Error getting gauges: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_gauge_needles(
    project_id: str, limit: Optional[int] = 100, page: Optional[int] = None
) -> Dict[str, Any]:
    """Get a project's gauge history, newest first."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        needles = await _run_sync(client.get_gauge_needles, project_id, limit, page)
        return {"status": "success", "needles": needles, "count": len(needles)}
    except Exception as e:
        logger.error(f"Error getting gauge needles for {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_gauge_needle(needle_id: str) -> Dict[str, Any]:
    """Get one Basecamp gauge needle."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        needle = await _run_sync(client.get_gauge_needle, needle_id)
        return {"status": "success", "needle": needle}
    except Exception as e:
        logger.error(f"Error getting gauge needle {needle_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_gauge_needle(
    project_id: str,
    position: int,
    color: Optional[str] = None,
    description: Optional[str] = None,
    notify: Optional[str] = None,
    subscriptions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record a new progress update for a Basecamp project gauge."""
    if not isinstance(position, int) or isinstance(position, bool) or not 0 <= position <= 100:
        return _error_response("Invalid input", "position must be an integer between 0 and 100")
    if color is not None and color not in {"green", "yellow", "red"}:
        return _error_response("Invalid input", "color must be green, yellow, or red")
    if notify is not None and notify not in {"default", "everyone", "custom"}:
        return _error_response("Invalid input", "notify must be default, everyone, or custom")
    if notify == "custom" and not subscriptions:
        return _error_response("Invalid input", "subscriptions are required when notify is custom")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        needle = await _run_sync(
            client.create_gauge_needle,
            project_id,
            position,
            color,
            description,
            notify,
            subscriptions,
        )
        return {"status": "success", "needle": needle, "message": "Gauge needle created"}
    except Exception as e:
        logger.error(f"Error creating gauge needle for {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_gauge_needle(needle_id: str, description: str) -> Dict[str, Any]:
    """Update the description of a Basecamp gauge needle."""
    if description is None:
        return _error_response("Invalid input", "description is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        needle = await _run_sync(client.update_gauge_needle, needle_id, description)
        return {"status": "success", "needle": needle, "message": "Gauge needle updated"}
    except Exception as e:
        logger.error(f"Error updating gauge needle {needle_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def delete_gauge_needle(needle_id: str) -> Dict[str, Any]:
    """Permanently delete a Basecamp gauge needle."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.delete_gauge_needle, needle_id)
        return {"status": "success", "message": "Gauge needle deleted"}
    except Exception as e:
        logger.error(f"Error deleting gauge needle {needle_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def toggle_gauge(project_id: str, enabled: bool) -> Dict[str, Any]:
    """Enable or disable a Basecamp project's gauge."""
    if not isinstance(enabled, bool):
        return _error_response("Invalid input", "enabled must be a boolean")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.toggle_gauge, project_id, enabled)
        return {"status": "success", "message": "Gauge enabled" if enabled else "Gauge disabled"}
    except Exception as e:
        logger.error(f"Error toggling gauge for {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_lineup_markers() -> Dict[str, Any]:
    """List account-wide Basecamp Lineup markers."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        markers = await _run_sync(client.get_lineup_markers)
        return {"status": "success", "markers": markers, "count": len(markers)}
    except Exception as e:
        logger.error(f"Error getting Lineup markers: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_lineup_marker(name: str, date: str) -> Dict[str, Any]:
    """Create an account-wide Basecamp Lineup marker."""
    if not name:
        return _error_response("Invalid input", "name is required")
    if not date:
        return _error_response("Invalid input", "date is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.create_lineup_marker, name, date)
        return {"status": "success", "message": "Lineup marker created"}
    except Exception as e:
        logger.error(f"Error creating Lineup marker: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_lineup_marker(
    marker_id: str,
    name: Optional[str] = None,
    date: Optional[str] = None,
) -> Dict[str, Any]:
    """Update an account-wide Basecamp Lineup marker."""
    if name is None and date is None:
        return _error_response("Invalid input", "name or date is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.update_lineup_marker, marker_id, name, date)
        return {"status": "success", "message": "Lineup marker updated"}
    except Exception as e:
        logger.error(f"Error updating Lineup marker {marker_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def delete_lineup_marker(marker_id: str) -> Dict[str, Any]:
    """Delete an account-wide Basecamp Lineup marker."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.delete_lineup_marker, marker_id)
        return {"status": "success", "message": "Lineup marker deleted"}
    except Exception as e:
        logger.error(f"Error deleting Lineup marker {marker_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_question_reminders(limit: Optional[int] = None) -> Dict[str, Any]:
    """Get pending automatic check-in reminders for the authenticated user.

    Args:
        limit: Optional maximum number of reminders to return.
    """
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")

    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        reminders = await _run_sync(client.get_question_reminders, limit)
        return {"status": "success", "reminders": reminders, "count": len(reminders)}
    except Exception as e:
        logger.error(f"Error getting question reminders: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_my_bookmarks(limit: Optional[int] = None) -> Dict[str, Any]:
    """Get recordings bookmarked by the authenticated user."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        bookmarks = await _run_sync(client.get_my_bookmarks, limit)
        return {"status": "success", "bookmarks": bookmarks, "count": len(bookmarks)}
    except Exception as e:
        logger.error(f"Error getting bookmarks: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_bookmark_status(recording_id: str) -> Dict[str, Any]:
    """Get the authenticated user's bookmark status for a recording."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        bookmark = await _run_sync(client.get_bookmark_status, recording_id)
        return {"status": "success", "bookmark": bookmark}
    except Exception as e:
        logger.error(f"Error getting bookmark status for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_bookmark(recording_id: str) -> Dict[str, Any]:
    """Bookmark a Basecamp recording for the authenticated user."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.create_bookmark, recording_id)
        return {"status": "success", "message": "Recording bookmarked"}
    except Exception as e:
        logger.error(f"Error creating bookmark for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def delete_bookmark(recording_id: str) -> Dict[str, Any]:
    """Remove a recording from the authenticated user's bookmarks."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.delete_bookmark, recording_id)
        return {"status": "success", "message": "Bookmark removed"}
    except Exception as e:
        logger.error(f"Error deleting bookmark for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_my_drafts(limit: Optional[int] = None) -> Dict[str, Any]:
    """Get unpublished drafts owned by the authenticated user."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        drafts = await _run_sync(client.get_my_drafts, limit)
        return {"status": "success", "drafts": drafts, "count": len(drafts)}
    except Exception as e:
        logger.error(f"Error getting drafts: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_my_note() -> Dict[str, Any]:
    """Get the authenticated user's personal Basecamp note."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        note = await _run_sync(client.get_my_note)
        return {"status": "success", "note": note}
    except Exception as e:
        logger.error(f"Error getting personal note: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_my_note(content: str) -> Dict[str, Any]:
    """Replace the authenticated user's personal Basecamp note."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        note = await _run_sync(client.update_my_note, content)
        return {"status": "success", "note": note}
    except Exception as e:
        logger.error(f"Error updating personal note: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_calendar(calendar_id: str) -> Dict[str, Any]:
    """Get a Basecamp calendar by ID."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        calendar = await _run_sync(client.get_calendar, calendar_id)
        return {"status": "success", "calendar": calendar}
    except Exception as e:
        logger.error(f"Error getting calendar {calendar_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_calendar(calendar_id: str, color: str) -> Dict[str, Any]:
    """Update a Basecamp calendar's display color."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        calendar = await _run_sync(client.update_calendar, calendar_id, color)
        return {"status": "success", "calendar": calendar}
    except ValueError as e:
        return _error_response("Invalid input", str(e))
    except Exception as e:
        logger.error(f"Error updating calendar {calendar_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_notifications(page: Optional[int] = None, limit_bubble_ups: bool = False) -> Dict[str, Any]:
    """Get the authenticated user's grouped Basecamp notification inbox."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        notifications = await _run_sync(client.get_notifications, page, limit_bubble_ups)
        return {"status": "success", "notifications": notifications}
    except Exception as e:
        logger.error(f"Error getting notifications: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_bubble_ups() -> Dict[str, Any]:
    """Get the authenticated user's current and scheduled bubble-ups."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        bubble_ups = await _run_sync(client.get_bubble_ups)
        return {"status": "success", "bubble_ups": bubble_ups, "count": len(bubble_ups)}
    except Exception as e:
        logger.error(f"Error getting bubble-ups: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def mark_notifications_read(readables: List[str]) -> Dict[str, Any]:
    """Mark notification readable SGIDs as read."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.mark_notifications_read, readables)
        return {"status": "success", "message": "Notifications marked as read"}
    except Exception as e:
        logger.error(f"Error marking notifications read: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_subscription(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Get subscription state and subscribers for a Basecamp recording."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        subscription = await _run_sync(client.get_subscription, project_id, recording_id)
        return {"status": "success", "subscription": subscription}
    except Exception as e:
        logger.error(f"Error getting subscription for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def subscribe_to_recording(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Subscribe the authenticated user to a Basecamp recording."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        subscription = await _run_sync(client.subscribe_to_recording, project_id, recording_id)
        return {"status": "success", "subscription": subscription}
    except Exception as e:
        logger.error(f"Error subscribing to {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def unsubscribe_from_recording(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Unsubscribe the authenticated user from a Basecamp recording."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.unsubscribe_from_recording, project_id, recording_id)
        return {"status": "success", "message": "Unsubscribed from recording"}
    except Exception as e:
        logger.error(f"Error unsubscribing from {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_subscription(
    project_id: str,
    recording_id: str,
    subscriptions: Optional[List[str]] = None,
    unsubscriptions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Add or remove people from a recording's subscriber list."""
    if not subscriptions and not unsubscriptions:
        return _error_response(
            "Invalid input", "subscriptions or unsubscriptions is required"
        )
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        subscription = await _run_sync(
            client.update_subscription,
            project_id,
            recording_id,
            subscriptions,
            unsubscriptions,
        )
        return {"status": "success", "subscription": subscription}
    except Exception as e:
        logger.error(f"Error updating subscription for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def prioritize_assignment(recording_id: str) -> Dict[str, Any]:
    """Add an assignment to the authenticated user's Up Next list."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.prioritize_assignment, recording_id)
        return {"status": "success", "message": "Assignment prioritized"}
    except Exception as e:
        logger.error(f"Error prioritizing assignment {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def deprioritize_assignment(recording_id: str) -> Dict[str, Any]:
    """Remove an assignment from the authenticated user's Up Next list."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.deprioritize_assignment, recording_id)
        return {"status": "success", "message": "Assignment deprioritized"}
    except Exception as e:
        logger.error(f"Error deprioritizing assignment {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def reorder_priority(recording_id: str, position: int) -> Dict[str, Any]:
    """Move an assignment to a position in the authenticated user's Up Next list."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.reorder_priority, recording_id, position)
        return {"status": "success", "message": "Assignment priority reordered"}
    except Exception as e:
        logger.error(f"Error reordering priority for {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_project(project_id: str) -> Dict[str, Any]:
    """Get details for a specific project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        project = await _run_sync(client.get_project, project_id)
        return {
            "status": "success",
            "project": project
        }
    except Exception as e:
        logger.error(f"Error getting project {project_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_schedule(project_id: str) -> Dict[str, Any]:
    """Get the schedule for a Basecamp project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        schedule = await _run_sync(client.get_schedule, project_id)
        return {
            "status": "success",
            "schedule": schedule
        }
    except Exception as e:
        logger.error(f"Error getting schedule for project {project_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_schedule_entries(project_id: str) -> Dict[str, Any]:
    """Get schedule entries for a Basecamp project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        entries = await _run_sync(client.get_schedule_entries, project_id)
        return {
            "status": "success",
            "entries": entries,
            "count": len(entries)
        }
    except Exception as e:
        logger.error(f"Error getting schedule entries for project {project_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_schedule_entry(project_id: str, entry_id: str) -> Dict[str, Any]:
    """Get one schedule entry from a Basecamp project."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        entry = await _run_sync(client.get_schedule_entry, project_id, entry_id)
        return {"status": "success", "entry": entry}
    except Exception as e:
        logger.error(f"Error getting schedule entry {entry_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_schedule_entry_occurrence(
    project_id: str, entry_id: str, date: str
) -> Dict[str, Any]:
    """Get one occurrence of a recurring schedule entry.

    Args:
        project_id: The project ID
        entry_id: The recurring schedule entry ID
        date: Occurrence date in YYYY-MM-DD format
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        occurrence = await _run_sync(
            client.get_schedule_entry_occurrence, project_id, entry_id, date
        )
        return {"status": "success", "occurrence": occurrence}
    except Exception as e:
        logger.error(f"Error getting schedule entry occurrence {entry_id}/{date}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_schedule_entry(
    project_id: str,
    summary: str,
    starts_at: str,
    ends_at: str,
    description: Optional[str] = None,
    participant_ids: Optional[List[str]] = None,
    all_day: Optional[bool] = None,
    notify: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a schedule entry in a Basecamp project's schedule.

    Args:
        project_id: The project ID
        summary: What the schedule entry is about
        starts_at: Start date/time in ISO 8601 format
        ends_at: End date/time in ISO 8601 format
        description: Optional HTML description
        participant_ids: Optional people IDs to invite
        all_day: Whether this is an all-day entry
        notify: Whether to notify participants
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        entry = await _run_sync(
            client.create_schedule_entry,
            project_id,
            summary,
            starts_at,
            ends_at,
            description=description,
            participant_ids=participant_ids,
            all_day=all_day,
            notify=notify,
        )
        return {"status": "success", "entry": entry}
    except Exception as e:
        logger.error(f"Error creating schedule entry in project {project_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_schedule_entry(
    project_id: str,
    entry_id: str,
    summary: Optional[str] = None,
    starts_at: Optional[str] = None,
    ends_at: Optional[str] = None,
    description: Optional[str] = None,
    participant_ids: Optional[List[str]] = None,
    all_day: Optional[bool] = None,
    notify: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update one or more fields on a Basecamp schedule entry."""
    if all(value is None for value in (
        summary, starts_at, ends_at, description, participant_ids, all_day, notify
    )):
        return _error_response(
            "Invalid input", "at least one schedule entry field must be provided"
        )

    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        entry = await _run_sync(
            client.update_schedule_entry,
            project_id,
            entry_id,
            summary=summary,
            starts_at=starts_at,
            ends_at=ends_at,
            description=description,
            participant_ids=participant_ids,
            all_day=all_day,
            notify=notify,
        )
        return {"status": "success", "entry": entry}
    except Exception as e:
        logger.error(f"Error updating schedule entry {entry_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def search_basecamp(query: str, project_id: Optional[str] = None) -> Dict[str, Any]:
    """Search across Basecamp projects, todos, and messages.

    Args:
        query: Search query
        project_id: Optional project ID to limit search scope
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        search = BasecampSearch(client=client)
        results = {}

        if project_id:
            # Search within specific project
            results["todolists"] = await _run_sync(search.search_todolists, query, project_id)
            results["todos"] = await _run_sync(search.search_todos, query, project_id)
        else:
            # Search across all projects
            results["projects"] = await _run_sync(search.search_projects, query)
            results["todos"] = await _run_sync(search.search_todos, query)
            results["messages"] = await _run_sync(search.search_messages, query)

        return {
            "status": "success",
            "query": query,
            "results": results
        }
    except Exception as e:
        logger.error(f"Error searching Basecamp: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_todolists(project_id: str) -> Dict[str, Any]:
    """Get todo lists for a project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        todolists = await _run_sync(client.get_todolists, project_id)
        return {
            "status": "success",
            "todolists": todolists,
            "count": len(todolists)
        }
    except Exception as e:
        logger.error(f"Error getting todolists: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_todos(
    project_id: str,
    todolist_id: str,
    completed: bool = False,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Get todos from a todo list.

    Args:
        project_id: Project ID
        todolist_id: The todo list ID
        completed: Return completed todos instead of the default active set
        status: Optional recording status filter: archived or trashed
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        todos = await _run_sync(
            client.get_todos, project_id, todolist_id, completed, status
        )
        return {
            "status": "success",
            "todos": todos,
            "count": len(todos)
        }
    except Exception as e:
        logger.error(f"Error getting todos: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_todo(project_id: str, todo_id: str) -> Dict[str, Any]:
    """Get a single todo item by its ID.

    Args:
        project_id: Project ID
        todo_id: The todo ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        todo = await _run_sync(client.get_todo, project_id, todo_id)
        return {
            "status": "success",
            "todo": todo
        }
    except Exception as e:
        logger.error(f"Error getting todo {todo_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_todo(project_id: str, todolist_id: str, content: str,
                     description: Optional[str] = None,
                     assignee_ids: Optional[List[str]] = None,
                     completion_subscriber_ids: Optional[List[str]] = None,
                     notify: bool = False,
                     due_on: Optional[str] = None,
                     starts_on: Optional[str] = None) -> Dict[str, Any]:
    """Create a new todo item in a todo list.

    Args:
        project_id: Project ID
        todolist_id: The todo list ID
        content: The todo item's text (required)
        description: HTML description of the todo
        assignee_ids: List of person IDs to assign
        completion_subscriber_ids: List of person IDs to notify on completion
        notify: Whether to notify assignees
        due_on: Due date in YYYY-MM-DD format
        starts_on: Start date in YYYY-MM-DD format
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        # Use lambda to properly handle keyword arguments
        todo = await _run_sync(
            lambda: client.create_todo(
                project_id, todolist_id, content,
                description=description,
                assignee_ids=assignee_ids,
                completion_subscriber_ids=completion_subscriber_ids,
                notify=notify,
                due_on=due_on,
                starts_on=starts_on
            )
        )
        return {
            "status": "success",
            "todo": todo,
            "message": f"Todo '{content}' created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating todo: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def update_todo(project_id: str, todo_id: str,
                     content: Optional[str] = None,
                     description: Optional[str] = None,
                     assignee_ids: Optional[List[str]] = None,
                     completion_subscriber_ids: Optional[List[str]] = None,
                     notify: Optional[bool] = None,
                     due_on: Optional[str] = None,
                     starts_on: Optional[str] = None) -> Dict[str, Any]:
    """Update an existing todo item.

    Args:
        project_id: Project ID
        todo_id: The todo ID
        content: The todo item's text
        description: HTML description of the todo
        assignee_ids: List of person IDs to assign
        completion_subscriber_ids: List of person IDs to notify on completion
        due_on: Due date in YYYY-MM-DD format
        starts_on: Start date in YYYY-MM-DD format
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        # Guard against no-op updates
        if all(v is None for v in [content, description, assignee_ids,
                                   completion_subscriber_ids, notify,
                                   due_on, starts_on]):
            return {
                "error": "Invalid input",
                "message": "At least one field to update must be provided"
            }
        # Use lambda to properly handle keyword arguments
        todo = await _run_sync(
            lambda: client.update_todo(
                project_id, todo_id,
                content=content,
                description=description,
                assignee_ids=assignee_ids,
                completion_subscriber_ids=completion_subscriber_ids,
                notify=notify,
                due_on=due_on,
                starts_on=starts_on
            )
        )
        return {
            "status": "success",
            "todo": todo,
            "message": "Todo updated successfully"
        }
    except Exception as e:
        logger.error(f"Error updating todo: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def delete_todo(project_id: str, todo_id: str) -> Dict[str, Any]:
    """Move a todo item to the trash.

    Trashed todos can be recovered from the Basecamp web UI within 30 days.

    Args:
        project_id: Project ID
        todo_id: The todo ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.delete_todo, project_id, todo_id)
        return {
            "status": "success",
            "message": "Todo moved to trash"
        }
    except Exception as e:
        logger.error(f"Error trashing todo: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def complete_todo(project_id: str, todo_id: str) -> Dict[str, Any]:
    """Mark a todo item as complete.

    Args:
        project_id: Project ID
        todo_id: The todo ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        completion = await _run_sync(client.complete_todo, project_id, todo_id)
        return {
            "status": "success",
            "completion": completion,
            "message": "Todo marked as complete"
        }
    except Exception as e:
        logger.error(f"Error completing todo: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def uncomplete_todo(project_id: str, todo_id: str) -> Dict[str, Any]:
    """Mark a todo item as incomplete.

    Args:
        project_id: Project ID
        todo_id: The todo ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.uncomplete_todo, project_id, todo_id)
        return {
            "status": "success",
            "message": "Todo marked as incomplete"
        }
    except Exception as e:
        logger.error(f"Error uncompleting todo: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def archive_todo(project_id: str, todo_id: str) -> Dict[str, Any]:
    """Archive a todo item.

    Archived todos are hidden from the active list but remain accessible
    via the Basecamp web UI.

    Args:
        project_id: Project ID
        todo_id: The todo ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.archive_todo, project_id, todo_id)
        return {"status": "success", "message": f"Todo {todo_id} archived"}
    except Exception as e:
        logger.error(f"Error archiving todo {todo_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def reposition_todo(
    project_id: str,
    todo_id: str,
    position: int,
    parent_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Reposition a todo within its list, or move it to another list or group.

    Args:
        project_id: The project ID
        todo_id: The todo ID
        position: New 1-based position within the target list
        parent_id: ID of the target todolist or group to move the todo into.
                   Omit to keep the todo in its current list and only change position.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    if position < 1:
        return {"error": "Invalid input", "message": "position must be >= 1"}

    try:
        await _run_sync(
            lambda: client.reposition_todo(project_id, todo_id, position, parent_id)
        )
        return {"status": "success", "message": f"Todo {todo_id} moved to position {position}"}
    except Exception as e:
        logger.error(f"Error repositioning todo {todo_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def global_search(query: str) -> Dict[str, Any]:
    """Search projects, todos and campfire messages across all projects.

    Args:
        query: Search query
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        search = BasecampSearch(client=client)
        results = await _run_sync(search.global_search, query)
        return {
            "status": "success",
            "query": query,
            "results": results
        }
    except Exception as e:
        logger.error(f"Error in global search: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_search_metadata() -> Dict[str, Any]:
    """Get the valid filters and content types for native Basecamp search."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        metadata = await _run_sync(client.get_search_metadata)
        return {"status": "success", "metadata": metadata}
    except Exception as e:
        logger.error(f"Error getting search metadata: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def search_recordings(
    query: str,
    type_names: Optional[List[str]] = None,
    bucket_ids: Optional[List[str]] = None,
    creator_ids: Optional[List[str]] = None,
    file_type: Optional[str] = None,
    exclude_chat: bool = False,
    since: Optional[str] = None,
    sort: Optional[str] = None,
    per_page: Optional[int] = None,
    limit: int = 100,
    page: Optional[int] = None,
) -> Dict[str, Any]:
    """Search Basecamp content, returning one page or at most ``limit`` results."""
    if per_page is not None and per_page < 1:
        return _error_response("Invalid input", "per_page must be >= 1")
    if limit < 1 or limit > 1000:
        return _error_response("Invalid input", "limit must be between 1 and 1000")
    if page is not None and page < 1:
        return _error_response("Invalid input", "page must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        results = await _run_sync(
            client.search_recordings,
            query,
            type_names,
            bucket_ids,
            creator_ids,
            file_type,
            exclude_chat,
            since,
            sort,
            per_page,
            limit,
            page,
        )
        return {"status": "success", "query": query, "results": results, "count": len(results)}
    except Exception as e:
        logger.error(f"Error searching recordings: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_comments(recording_id: str, project_id: str, page: int = 1) -> Dict[str, Any]:
    """Get comments for a Basecamp item.

    Args:
        recording_id: The item ID
        project_id: The project ID
        page: Page number for pagination (default: 1). Basecamp uses geared pagination:
              page 1 has 15 results, page 2 has 30, page 3 has 50, page 4+ has 100.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        result = await _run_sync(client.get_comments, project_id, recording_id, page)
        return {
            "status": "success",
            "comments": result["comments"],
            "count": len(result["comments"]),
            "page": page,
            "total_count": result["total_count"],
            "next_page": result["next_page"]
        }
    except Exception as e:
        logger.error(f"Error getting comments: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_comment(recording_id: str, project_id: str, content: str) -> Dict[str, Any]:
    """Create a comment on a Basecamp item.

    Args:
        recording_id: The item ID
        project_id: The project ID
        content: The comment content in HTML format
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        comment = await _run_sync(client.create_comment, recording_id, project_id, content)
        return {
            "status": "success",
            "comment": comment,
            "message": "Comment created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating comment: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_comment(comment_id: str, project_id: str) -> Dict[str, Any]:
    """Get a specific comment by ID.

    Args:
        comment_id: The comment ID
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        comment = await _run_sync(client.get_comment, comment_id, project_id)
        return {
            "status": "success",
            "comment": comment
        }
    except Exception as e:
        logger.error(f"Error getting comment {comment_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def update_comment(comment_id: str, project_id: str, content: str) -> Dict[str, Any]:
    """Update a comment's content.

    Args:
        comment_id: The comment ID
        project_id: The project ID
        content: The new comment content in HTML format
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        comment = await _run_sync(client.update_comment, comment_id, project_id, content)
        return {
            "status": "success",
            "comment": comment,
            "message": "Comment updated successfully"
        }
    except Exception as e:
        logger.error(f"Error updating comment {comment_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def delete_comment(comment_id: str, project_id: str) -> Dict[str, Any]:
    """Delete a comment.

    Args:
        comment_id: The comment ID
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.delete_comment, comment_id, project_id)
        return {
            "status": "success",
            "message": "Comment deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting comment {comment_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_campfire_lines(project_id: str, campfire_id: str) -> Dict[str, Any]:
    """Get recent messages from a Basecamp campfire (chat room).

    Args:
        project_id: The project ID
        campfire_id: The campfire/chat room ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        lines = await _run_sync(client.get_campfire_lines, project_id, campfire_id)
        return {
            "status": "success",
            "campfire_lines": lines,
            "count": len(lines)
        }
    except Exception as e:
        logger.error(f"Error getting campfire lines: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_campfires(project_id: str) -> Dict[str, Any]:
    """List campfire/chat rooms enabled in a project."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        campfires = await _run_sync(client.get_campfires, project_id)
        return {
            "status": "success",
            "campfires": campfires,
            "count": len(campfires),
        }
    except Exception as e:
        logger.error(f"Error getting campfires: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {
            "error": "Execution error",
            "message": str(e),
        }

@mcp.tool()
async def get_campfire_line(project_id: str, campfire_id: str, line_id: str) -> Dict[str, Any]:
    """Get one line from a Basecamp campfire."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        line = await _run_sync(client.get_campfire_line, project_id, campfire_id, line_id)
        return {"status": "success", "line": line}
    except Exception as e:
        logger.error(f"Error getting campfire line {line_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {"error": "Execution error", "message": str(e)}

@mcp.tool()
async def create_campfire_line(project_id: str, campfire_id: str, content: str) -> Dict[str, Any]:
    """Create a plain-text line in a Basecamp campfire."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        line = await _run_sync(client.create_campfire_line, project_id, campfire_id, content)
        return {
            "status": "success",
            "line": line,
            "message": "Campfire line created successfully",
        }
    except Exception as e:
        logger.error(f"Error creating campfire line: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {"error": "Execution error", "message": str(e)}

@mcp.tool()
async def delete_campfire_line(project_id: str, campfire_id: str, line_id: str) -> Dict[str, Any]:
    """Permanently delete a line from a Basecamp campfire."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.delete_campfire_line, project_id, campfire_id, line_id)
        return {
            "status": "success",
            "message": "Campfire line deleted successfully",
        }
    except Exception as e:
        logger.error(f"Error deleting campfire line {line_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {"error": "Execution error", "message": str(e)}

@mcp.tool()
async def get_message_board(project_id: str) -> Dict[str, Any]:
    """Get the message board for a project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        message_board = await _run_sync(client.get_message_board, project_id)
        return {
            "status": "success",
            "message_board": message_board
        }
    except Exception as e:
        logger.error(f"Error getting message board: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_messages(project_id: str, message_board_id: Optional[str] = None) -> Dict[str, Any]:
    """Get all messages from a project's message board.

    Args:
        project_id: The project ID
        message_board_id: Optional message board ID. If not provided, will be auto-discovered from the project.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        messages = await _run_sync(client.get_messages, project_id, message_board_id)
        return {
            "status": "success",
            "messages": messages,
            "count": len(messages)
        }
    except Exception as e:
        logger.error(f"Error getting messages: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_message(project_id: str, message_id: str) -> Dict[str, Any]:
    """Get a specific message by ID.

    Args:
        project_id: The project ID
        message_id: The message ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        message = await _run_sync(client.get_message, project_id, message_id)
        return {
            "status": "success",
            "message": message
        }
    except Exception as e:
        logger.error(f"Error getting message: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }


@mcp.tool()
async def get_message_categories(project_id: str) -> Dict[str, Any]:
    """Get message categories (types) for a project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        categories = await _run_sync(client.get_message_categories, project_id)
        return {
            "status": "success",
            "categories": categories,
            "count": len(categories)
        }
    except Exception as e:
        logger.error(f"Error getting message categories: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_message_category(project_id: str, category_id: str) -> Dict[str, Any]:
    """Get one message type/category."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        category = await _run_sync(client.get_message_category, project_id, category_id)
        return {"status": "success", "category": category}
    except Exception as e:
        logger.error(f"Error getting message category {category_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_message_category(project_id: str, name: str, icon: str) -> Dict[str, Any]:
    """Create a message type/category."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        category = await _run_sync(client.create_message_category, project_id, name, icon)
        return {"status": "success", "category": category, "message": "Message category created successfully"}
    except Exception as e:
        logger.error(f"Error creating message category: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_message_category(project_id: str, category_id: str, name: str, icon: str) -> Dict[str, Any]:
    """Update a message type/category."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        category = await _run_sync(client.update_message_category, project_id, category_id, name, icon)
        return {"status": "success", "category": category, "message": "Message category updated successfully"}
    except Exception as e:
        logger.error(f"Error updating message category {category_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def delete_message_category(project_id: str, category_id: str) -> Dict[str, Any]:
    """Delete a message type/category."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.delete_message_category, project_id, category_id)
        return {"status": "success", "message": "Message category deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting message category {category_id}: {e}")
        return _error_response("Execution error", str(e))


@mcp.tool()
async def create_message(project_id: str, subject: str, content: str,
                         message_board_id: Optional[str] = None,
                         category_id: Optional[str] = None,
                         publish: bool = True) -> Dict[str, Any]:
    """Create a new message on a project's message board.

    Args:
        project_id: The project ID
        subject: Message title/subject
        content: Message body in HTML format
        message_board_id: Optional message board ID. If not provided, will be auto-discovered from the project.
        category_id: Optional message type/category ID
        publish: When true, publish immediately. When false, create a draft.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        message = await _run_sync(
            lambda: client.create_message(
                project_id, subject, content,
                message_board_id=message_board_id,
                category_id=category_id,
                status="active" if publish else None
            )
        )
        return {
            "status": "success",
            "message": message,
            "result": f"Message '{subject}' {'published' if publish else 'drafted'} successfully"
        }
    except Exception as e:
        logger.error(f"Error creating message: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return _error_response(
                "OAuth token expired",
                "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            )
        return _error_response("Execution error", str(e))


@mcp.tool()
async def update_message(project_id: str, message_id: str,
                         subject: Optional[str] = None,
                         content: Optional[str] = None,
                         category_id: Optional[str] = None) -> Dict[str, Any]:
    """Update one or more fields on a message.

    Args:
        project_id: The project ID
        message_id: The message ID
        subject: Optional replacement title
        content: Optional replacement body in HTML format
        category_id: Optional replacement message category ID
    """
    if subject is None and content is None and category_id is None:
        return {
            "error": "Invalid input",
            "message": "At least one message field must be provided",
        }

    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        message = await _run_sync(
            client.update_message,
            project_id,
            message_id,
            subject,
            content,
            category_id,
        )
        return {
            "status": "success",
            "message": message,
            "result": "Message updated successfully",
        }
    except Exception as e:
        logger.error(f"Error updating message {message_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {
            "error": "Execution error",
            "message": str(e),
        }


@mcp.tool()
async def pin_message(project_id: str, message_id: str) -> Dict[str, Any]:
    """Pin a message to the top of its message board."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.pin_message, project_id, message_id)
        return {
            "status": "success",
            "message": "Message pinned successfully",
        }
    except Exception as e:
        logger.error(f"Error pinning message {message_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {
            "error": "Execution error",
            "message": str(e),
        }


@mcp.tool()
async def unpin_message(project_id: str, message_id: str) -> Dict[str, Any]:
    """Remove a message from the top of its message board."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.unpin_message, project_id, message_id)
        return {
            "status": "success",
            "message": "Message unpinned successfully",
        }
    except Exception as e:
        logger.error(f"Error unpinning message {message_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            }
        return {
            "error": "Execution error",
            "message": str(e),
        }


@mcp.tool()
async def create_draft_message(project_id: str, subject: str, content: str,
                               message_board_id: Optional[str] = None,
                               category_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a draft message on a project's message board without publishing it.

    Args:
        project_id: The project ID
        subject: Message title/subject
        content: Message body in HTML format
        message_board_id: Optional message board ID. If not provided, will be auto-discovered from the project.
        category_id: Optional message type/category ID
    """
    return await create_message(
        project_id,
        subject,
        content,
        message_board_id=message_board_id,
        category_id=category_id,
        publish=False,
    )


# Inbox Tools (Email Forwards)
@mcp.tool()
async def get_inbox(project_id: str) -> Dict[str, Any]:
    """Get the inbox for a project (for email forwards).

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        inbox = await _run_sync(client.get_inbox, project_id)
        return {
            "status": "success",
            "inbox": inbox
        }
    except Exception as e:
        logger.error(f"Error getting inbox: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }


@mcp.tool()
async def get_forwards(project_id: str, inbox_id: Optional[str] = None) -> Dict[str, Any]:
    """Get all forwarded emails from a project's inbox.

    Args:
        project_id: The project ID
        inbox_id: Optional inbox ID. If not provided, will be auto-discovered from the project.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        forwards = await _run_sync(client.get_forwards, project_id, inbox_id)
        return {
            "status": "success",
            "forwards": forwards,
            "count": len(forwards)
        }
    except Exception as e:
        logger.error(f"Error getting forwards: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }


@mcp.tool()
async def get_forward(project_id: str, forward_id: str) -> Dict[str, Any]:
    """Get a specific forwarded email by ID.

    Args:
        project_id: The project ID
        forward_id: The forward ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        forward = await _run_sync(client.get_forward, project_id, forward_id)
        return {
            "status": "success",
            "forward": forward
        }
    except Exception as e:
        logger.error(f"Error getting forward: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }


@mcp.tool()
async def get_inbox_replies(project_id: str, forward_id: str) -> Dict[str, Any]:
    """Get all replies to a forwarded email.

    Args:
        project_id: The project ID
        forward_id: The forward ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        replies = await _run_sync(client.get_inbox_replies, project_id, forward_id)
        return {
            "status": "success",
            "replies": replies,
            "count": len(replies)
        }
    except Exception as e:
        logger.error(f"Error getting inbox replies: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }


@mcp.tool()
async def get_inbox_reply(project_id: str, forward_id: str, reply_id: str) -> Dict[str, Any]:
    """Get a specific reply to a forwarded email.

    Args:
        project_id: The project ID
        forward_id: The forward ID
        reply_id: The reply ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        reply = await _run_sync(client.get_inbox_reply, project_id, forward_id, reply_id)
        return {
            "status": "success",
            "reply": reply
        }
    except Exception as e:
        logger.error(f"Error getting inbox reply: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }


@mcp.tool()
async def trash_forward(project_id: str, forward_id: str) -> Dict[str, Any]:
    """Move a forwarded email to trash.

    Args:
        project_id: The project ID
        forward_id: The forward ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.trash_forward, project_id, forward_id)
        return {
            "status": "success",
            "message": "Forward trashed"
        }
    except Exception as e:
        logger.error(f"Error trashing forward: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }


@mcp.tool()
async def get_card_tables(project_id: str) -> Dict[str, Any]:
    """Get all card tables for a project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        card_tables = await _run_sync(client.get_card_tables, project_id)
        return {
            "status": "success",
            "card_tables": card_tables,
            "count": len(card_tables)
        }
    except Exception as e:
        logger.error(f"Error getting card tables: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_card_table(project_id: str) -> Dict[str, Any]:
    """Get the card table details for a project.

    Args:
        project_id: The project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        card_table = await _run_sync(client.get_card_table, project_id)
        card_table_details = await _run_sync(client.get_card_table_details, project_id, card_table['id'])
        return {
            "status": "success",
            "card_table": card_table_details
        }
    except Exception as e:
        logger.error(f"Error getting card table: {e}")
        error_msg = str(e)
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "status": "error",
            "message": f"Error getting card table: {error_msg}",
            "debug": error_msg
        }

@mcp.tool()
async def get_columns(project_id: str, card_table_id: str) -> Dict[str, Any]:
    """Get all columns in a card table.

    Args:
        project_id: The project ID
        card_table_id: The card table ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        columns = await _run_sync(client.get_columns, project_id, card_table_id)
        return {
            "status": "success",
            "columns": columns,
            "count": len(columns)
        }
    except Exception as e:
        logger.error(f"Error getting columns: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_cards(project_id: str, column_id: str) -> Dict[str, Any]:
    """Get all cards in a column.

    Args:
        project_id: The project ID
        column_id: The column ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        cards = await _run_sync(client.get_cards, project_id, column_id)
        return {
            "status": "success",
            "cards": cards,
            "count": len(cards)
        }
    except Exception as e:
        logger.error(f"Error getting cards: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_card(project_id: str, column_id: str, title: str, content: Optional[str] = None, due_on: Optional[str] = None, notify: bool = False) -> Dict[str, Any]:
    """Create a new card in a column.

    Args:
        project_id: The project ID
        column_id: The column ID
        title: The card title
        content: Optional card content/description
        due_on: Optional due date (ISO 8601 format)
        notify: Whether to notify assignees (default: false)
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        card = await _run_sync(client.create_card, project_id, column_id, title, content, due_on, notify)
        return {
            "status": "success",
            "card": card,
            "message": f"Card '{title}' created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating card: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_column(project_id: str, column_id: str) -> Dict[str, Any]:
    """Get details for a specific column.

    Args:
        project_id: The project ID
        column_id: The column ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        column = await _run_sync(client.get_column, project_id, column_id)
        return {
            "status": "success",
            "column": column
        }
    except Exception as e:
        logger.error(f"Error getting column: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_column(project_id: str, card_table_id: str, title: str) -> Dict[str, Any]:
    """Create a new column in a card table.

    Args:
        project_id: The project ID
        card_table_id: The card table ID
        title: The column title
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        column = await _run_sync(client.create_column, project_id, card_table_id, title)
        return {
            "status": "success",
            "column": column,
            "message": f"Column '{title}' created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating column: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def move_card(
    project_id: str,
    card_id: str,
    column_id: str,
    position: Optional[int] = None,
) -> Dict[str, Any]:
    """Move a card to a column or linked cross-project wormhole.

    Args:
        project_id: The project ID
        card_id: The card ID
        column_id: The destination column or wormhole ID
        position: Optional positive position within the destination column
    """
    if position is not None and (isinstance(position, bool) or not isinstance(position, int) or position < 1):
        return _error_response("Invalid input", "position must be a positive integer")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        if position is None:
            await _run_sync(client.move_card, project_id, card_id, column_id)
        else:
            await _run_sync(client.move_card, project_id, card_id, column_id, position)
        return {
            "status": "success",
            "message": f"Card moved to column {column_id}"
        }
    except Exception as e:
        logger.error(f"Error moving card: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_card_table_wormhole(
    project_id: str, card_table_id: str, destination_recording_id: str
) -> Dict[str, Any]:
    """Create a cross-project card-table wormhole."""
    if not destination_recording_id:
        return _error_response("Invalid input", "destination_recording_id is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        wormhole = await _run_sync(
            client.create_card_table_wormhole,
            project_id,
            card_table_id,
            destination_recording_id,
        )
        return {"status": "success", "wormhole": wormhole, "message": "Wormhole created"}
    except Exception as e:
        logger.error(f"Error creating wormhole for card table {card_table_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_card_table_wormhole(
    project_id: str, wormhole_id: str, destination_recording_id: str
) -> Dict[str, Any]:
    """Change a card-table wormhole's destination column."""
    if not destination_recording_id:
        return _error_response("Invalid input", "destination_recording_id is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        wormhole = await _run_sync(
            client.update_card_table_wormhole,
            project_id,
            wormhole_id,
            destination_recording_id,
        )
        return {"status": "success", "wormhole": wormhole, "message": "Wormhole updated"}
    except Exception as e:
        logger.error(f"Error updating wormhole {wormhole_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def delete_card_table_wormhole(project_id: str, wormhole_id: str) -> Dict[str, Any]:
    """Delete a card-table wormhole."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.delete_card_table_wormhole, project_id, wormhole_id)
        return {"status": "success", "message": "Wormhole deleted"}
    except Exception as e:
        logger.error(f"Error deleting wormhole {wormhole_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def complete_card(project_id: str, card_id: str) -> Dict[str, Any]:
    """Mark a card as complete.

    Args:
        project_id: The project ID
        card_id: The card ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.complete_card, project_id, card_id)
        return {
            "status": "success",
            "message": "Card marked as complete"
        }
    except Exception as e:
        logger.error(f"Error completing card: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_card(project_id: str, card_id: str) -> Dict[str, Any]:
    """Get details for a specific card.

    Args:
        project_id: The project ID
        card_id: The card ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        card = await _run_sync(client.get_card, project_id, card_id)
        return {
            "status": "success",
            "card": card
        }
    except Exception as e:
        logger.error(f"Error getting card: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def update_card(project_id: str, card_id: str, title: Optional[str] = None, content: Optional[str] = None, due_on: Optional[str] = None, assignee_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Update a card.

    Args:
        project_id: The project ID
        card_id: The card ID
        title: The new card title
        content: The new card content/description
        due_on: Due date (ISO 8601 format)
        assignee_ids: Array of person IDs to assign to the card
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        card = await _run_sync(client.update_card, project_id, card_id, title, content, due_on, assignee_ids)
        return {
            "status": "success",
            "card": card,
            "message": "Card updated successfully"
        }
    except Exception as e:
        logger.error(f"Error updating card: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_daily_check_ins(project_id: str, page: Optional[int] = None) -> Dict[str, Any]:
    """Get project's daily checking questionnaire.

    Args:
        project_id: The project ID
        page: Page number paginated response
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        if page is not None and not isinstance(page, int):
            page = 1
        questions = await _run_sync(client.get_daily_check_ins, project_id, page)
        return {
            "status": "success",
            "questions": questions,
            # Retain the historical key for clients that consumed the old response shape.
            "campfire_lines": questions,
            "count": len(questions)
        }
    except Exception as e:
        logger.error(f"Error getting daily check ins: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_question_answers(project_id: str, question_id: str, page: Optional[int] = None) -> Dict[str, Any]:
    """Get answers on daily check-in question.

    Args:
        project_id: The project ID
        question_id: The question ID
        page: Page number paginated response
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        if page is not None and not isinstance(page, int):
            page = 1
        answers = await _run_sync(client.get_question_answers, project_id, question_id, page)
        return {
            "status": "success",
            "answers": answers,
            # Retain the historical key for clients that consumed the old response shape.
            "campfire_lines": answers,
            "count": len(answers)
        }
    except Exception as e:
        logger.error(f"Error getting question answers: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_questionnaire(project_id: str, questionnaire_id: Optional[str] = None) -> Dict[str, Any]:
    """Get the automatic check-ins questionnaire for a project."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        questionnaire = await _run_sync(client.get_questionnaire, project_id, questionnaire_id)
        return {"status": "success", "questionnaire": questionnaire}
    except Exception as e:
        logger.error(f"Error getting questionnaire: {e}")
        return {"error": "Execution error", "message": str(e)}

@mcp.tool()
async def get_questions(project_id: str, questionnaire_id: Optional[str] = None, page: Optional[int] = None) -> Dict[str, Any]:
    """Get questions from an automatic check-ins questionnaire."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        questions = await _run_sync(client.get_questions, project_id, questionnaire_id, page)
        return {"status": "success", "questions": questions, "count": len(questions)}
    except Exception as e:
        logger.error(f"Error getting questions: {e}")
        return {"error": "Execution error", "message": str(e)}

@mcp.tool()
async def get_question(project_id: str, question_id: str) -> Dict[str, Any]:
    """Get one automatic check-in question."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        question = await _run_sync(client.get_question, project_id, question_id)
        return {"status": "success", "question": question}
    except Exception as e:
        logger.error(f"Error getting question {question_id}: {e}")
        return {"error": "Execution error", "message": str(e)}

@mcp.tool()
async def create_question(
    questionnaire_id: str,
    title: str,
    schedule: Dict[str, Any],
    visible_to_clients: Optional[bool] = None,
) -> Dict[str, Any]:
    """Create a question in a Basecamp automatic check-ins questionnaire."""
    if not title:
        return _error_response("Invalid input", "title is required")
    if not isinstance(schedule, dict) or not schedule:
        return _error_response("Invalid input", "schedule must be a non-empty object")
    if visible_to_clients is not None and not isinstance(visible_to_clients, bool):
        return _error_response("Invalid input", "visible_to_clients must be a boolean")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        question = await _run_sync(
            client.create_question,
            questionnaire_id,
            title,
            schedule,
            visible_to_clients,
        )
        return {"status": "success", "question": question, "message": "Question created"}
    except Exception as e:
        logger.error(f"Error creating question in questionnaire {questionnaire_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_question(
    question_id: str,
    title: Optional[str] = None,
    schedule: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Update selected fields on a Basecamp automatic check-in question."""
    if title is None and schedule is None:
        return _error_response("Invalid input", "title or schedule is required")
    if title == "":
        return _error_response("Invalid input", "title must not be empty")
    if schedule is not None and (not isinstance(schedule, dict) or not schedule):
        return _error_response("Invalid input", "schedule must be a non-empty object")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        question = await _run_sync(client.update_question, question_id, title, schedule)
        return {"status": "success", "question": question, "message": "Question updated"}
    except Exception as e:
        logger.error(f"Error updating question {question_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def pause_question(question_id: str) -> Dict[str, Any]:
    """Pause a Basecamp automatic check-in question."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        question = await _run_sync(client.pause_question, question_id)
        return {"status": "success", "question": question, "message": "Question paused"}
    except Exception as e:
        logger.error(f"Error pausing question {question_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def resume_question(question_id: str) -> Dict[str, Any]:
    """Resume a paused Basecamp automatic check-in question."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        question = await _run_sync(client.resume_question, question_id)
        return {"status": "success", "question": question, "message": "Question resumed"}
    except Exception as e:
        logger.error(f"Error resuming question {question_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_question_notification_settings(
    question_id: str,
    responding: Optional[bool] = None,
    subscribed: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update the authenticated user's automatic check-in notification settings."""
    if responding is None and subscribed is None:
        return _error_response(
            "Invalid input",
            "responding or subscribed is required",
        )
    if responding is not None and not isinstance(responding, bool):
        return _error_response("Invalid input", "responding must be a boolean")
    if subscribed is not None and not isinstance(subscribed, bool):
        return _error_response("Invalid input", "subscribed must be a boolean")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        settings = await _run_sync(
            client.update_question_notification_settings,
            question_id,
            responding,
            subscribed,
        )
        return {"status": "success", "settings": settings}
    except Exception as e:
        logger.error(f"Error updating question settings {question_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_question_answerers(
    question_id: str, limit: Optional[int] = 100
) -> Dict[str, Any]:
    """List people who have answered a Basecamp automatic check-in question."""
    if limit is not None and limit < 1:
        return _error_response("Invalid input", "limit must be >= 1")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        answerers = await _run_sync(client.get_question_answerers, question_id, limit)
        return {"status": "success", "answerers": answerers, "count": len(answerers)}
    except Exception as e:
        logger.error(f"Error getting answerers for question {question_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_question_answer(project_id: str, answer_id: str) -> Dict[str, Any]:
    """Get one automatic check-in answer."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        answer = await _run_sync(client.get_question_answer, project_id, answer_id)
        return {"status": "success", "answer": answer}
    except Exception as e:
        logger.error(f"Error getting question answer {answer_id}: {e}")
        return {"error": "Execution error", "message": str(e)}

# Column Management Tools
@mcp.tool()
async def update_column(project_id: str, column_id: str, title: str) -> Dict[str, Any]:
    """Update a column title.

    Args:
        project_id: The project ID
        column_id: The column ID
        title: The new column title
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        column = await _run_sync(client.update_column, project_id, column_id, title)
        return {
            "status": "success",
            "column": column,
            "message": "Column updated successfully"
        }
    except Exception as e:
        logger.error(f"Error updating column: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def move_column(project_id: str, card_table_id: str, column_id: str, position: int) -> Dict[str, Any]:
    """Move a column to a new position.

    Args:
        project_id: The project ID
        card_table_id: The card table ID
        column_id: The column ID
        position: The new 1-based position
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.move_column, project_id, column_id, position, card_table_id)
        return {
            "status": "success",
            "message": f"Column moved to position {position}"
        }
    except Exception as e:
        logger.error(f"Error moving column: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def update_column_color(project_id: str, column_id: str, color: str) -> Dict[str, Any]:
    """Update a column color.

    Args:
        project_id: The project ID
        column_id: The column ID
        color: The hex color code (e.g., #FF0000)
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        column = await _run_sync(client.update_column_color, project_id, column_id, color)
        return {
            "status": "success",
            "column": column,
            "message": f"Column color updated to {color}"
        }
    except Exception as e:
        logger.error(f"Error updating column color: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def put_column_on_hold(project_id: str, column_id: str) -> Dict[str, Any]:
    """Put a column on hold (freeze work).

    Args:
        project_id: The project ID
        column_id: The column ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.put_column_on_hold, project_id, column_id)
        return {
            "status": "success",
            "message": "Column put on hold"
        }
    except Exception as e:
        logger.error(f"Error putting column on hold: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def remove_column_hold(project_id: str, column_id: str) -> Dict[str, Any]:
    """Remove hold from a column (unfreeze work).

    Args:
        project_id: The project ID
        column_id: The column ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.remove_column_hold, project_id, column_id)
        return {
            "status": "success",
            "message": "Column hold removed"
        }
    except Exception as e:
        logger.error(f"Error removing column hold: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def watch_column(project_id: str, column_id: str) -> Dict[str, Any]:
    """Subscribe to notifications for changes in a column.

    Args:
        project_id: The project ID
        column_id: The column ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.watch_column, project_id, column_id)
        return {
            "status": "success",
            "message": "Column notifications enabled"
        }
    except Exception as e:
        logger.error(f"Error watching column: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def unwatch_column(project_id: str, column_id: str) -> Dict[str, Any]:
    """Unsubscribe from notifications for a column.

    Args:
        project_id: The project ID
        column_id: The column ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.unwatch_column, project_id, column_id)
        return {
            "status": "success",
            "message": "Column notifications disabled"
        }
    except Exception as e:
        logger.error(f"Error unwatching column: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

# More Card Management Tools
@mcp.tool()
async def uncomplete_card(project_id: str, card_id: str) -> Dict[str, Any]:
    """Mark a card as incomplete.

    Args:
        project_id: The project ID
        card_id: The card ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.uncomplete_card, project_id, card_id)
        return {
            "status": "success",
            "message": "Card marked as incomplete"
        }
    except Exception as e:
        logger.error(f"Error uncompleting card: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

# Card Steps (Sub-tasks) Management
@mcp.tool()
async def get_card_steps(project_id: str, card_id: str) -> Dict[str, Any]:
    """Get all steps (sub-tasks) for a card.

    Args:
        project_id: The project ID
        card_id: The card ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        steps = await _run_sync(client.get_card_steps, project_id, card_id)
        return {
            "status": "success",
            "steps": steps,
            "count": len(steps)
        }
    except Exception as e:
        logger.error(f"Error getting card steps: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_card_step(project_id: str, card_id: str, title: str, due_on: Optional[str] = None, assignee_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Create a new step (sub-task) for a card.

    Args:
        project_id: The project ID
        card_id: The card ID
        title: The step title
        due_on: Optional due date (ISO 8601 format)
        assignee_ids: Array of person IDs to assign to the step
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        step = await _run_sync(client.create_card_step, project_id, card_id, title, due_on, assignee_ids)
        return {
            "status": "success",
            "step": step,
            "message": f"Step '{title}' created successfully"
        }
    except Exception as e:
        logger.error(f"Error creating card step: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_card_step(project_id: str, step_id: str) -> Dict[str, Any]:
    """Get details for a specific card step.

    Args:
        project_id: The project ID
        step_id: The step ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        step = await _run_sync(client.get_card_step, project_id, step_id)
        return {
            "status": "success",
            "step": step
        }
    except Exception as e:
        logger.error(f"Error getting card step: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def update_card_step(project_id: str, step_id: str, title: Optional[str] = None, due_on: Optional[str] = None, assignee_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Update a card step.

    Args:
        project_id: The project ID
        step_id: The step ID
        title: The step title
        due_on: Due date (ISO 8601 format)
        assignee_ids: Array of person IDs to assign to the step
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        step = await _run_sync(client.update_card_step, project_id, step_id, title, due_on, assignee_ids)
        return {
            "status": "success",
            "step": step,
            "message": f"Step updated successfully"
        }
    except Exception as e:
        logger.error(f"Error updating card step: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def delete_card_step(project_id: str, step_id: str) -> Dict[str, Any]:
    """Delete a card step.

    Args:
        project_id: The project ID
        step_id: The step ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.delete_card_step, project_id, step_id)
        return {
            "status": "success",
            "message": "Step deleted successfully"
        }
    except Exception as e:
        logger.error(f"Error deleting card step: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def complete_card_step(project_id: str, step_id: str) -> Dict[str, Any]:
    """Mark a card step as complete.

    Args:
        project_id: The project ID
        step_id: The step ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.complete_card_step, project_id, step_id)
        return {
            "status": "success",
            "message": "Step marked as complete"
        }
    except Exception as e:
        logger.error(f"Error completing card step: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def uncomplete_card_step(project_id: str, step_id: str) -> Dict[str, Any]:
    """Mark a card step as incomplete.

    Args:
        project_id: The project ID
        step_id: The step ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.uncomplete_card_step, project_id, step_id)
        return {
            "status": "success",
            "message": "Step marked as incomplete"
        }
    except Exception as e:
        logger.error(f"Error uncompleting card step: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

# Attachments, Events, and Webhooks
@mcp.tool()
async def create_attachment(file_path: str, name: str, content_type: Optional[str] = None) -> Dict[str, Any]:
    """Upload a file as an attachment.

    Args:
        file_path: Local path to file
        name: Filename for Basecamp
        content_type: MIME type
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        result = await _run_sync(client.create_attachment, file_path, name, content_type or "application/octet-stream")
        return {
            "status": "success",
            "attachment": result
        }
    except Exception as e:
        logger.error(f"Error creating attachment: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_events(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Get events for a recording.

    Args:
        project_id: Project ID
        recording_id: Recording ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        events = await _run_sync(client.get_events, project_id, recording_id)
        return {
            "status": "success",
            "events": events,
            "count": len(events)
        }
    except Exception as e:
        logger.error(f"Error getting events: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_webhooks(project_id: str) -> Dict[str, Any]:
    """List webhooks for a project.

    Args:
        project_id: Project ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        hooks = await _run_sync(client.get_webhooks, project_id)
        return {
            "status": "success",
            "webhooks": hooks,
            "count": len(hooks)
        }
    except Exception as e:
        logger.error(f"Error getting webhooks: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_webhook(project_id: str, webhook_id: str) -> Dict[str, Any]:
    """Get one project webhook and its recent deliveries."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        hook = await _run_sync(client.get_webhook, project_id, webhook_id)
        return {"status": "success", "webhook": hook}
    except Exception as e:
        logger.error(f"Error getting webhook {webhook_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_webhook(
    project_id: str,
    webhook_id: str,
    payload_url: str,
    types: Optional[List[str]] = None,
    active: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update a project webhook destination, event types, or active state."""
    try:
        BasecampClient._validate_webhook_url(payload_url)
    except ValueError as e:
        return _error_response("Invalid input", str(e))
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        hook = await _run_sync(
            client.update_webhook, project_id, webhook_id, payload_url, types, active
        )
        return {"status": "success", "webhook": hook}
    except Exception as e:
        logger.error(f"Error updating webhook {webhook_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_webhook(project_id: str, payload_url: str, types: Optional[List[str]] = None) -> Dict[str, Any]:
    """Create a webhook.

    Args:
        project_id: Project ID
        payload_url: Payload URL
        types: Event types
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        hook = await _run_sync(client.create_webhook, project_id, payload_url, types)
        return {
            "status": "success",
            "webhook": hook
        }
    except Exception as e:
        logger.error(f"Error creating webhook: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def delete_webhook(project_id: str, webhook_id: str) -> Dict[str, Any]:
    """Delete a webhook.

    Args:
        project_id: Project ID
        webhook_id: Webhook ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.delete_webhook, project_id, webhook_id)
        return {
            "status": "success",
            "message": "Webhook deleted"
        }
    except Exception as e:
        logger.error(f"Error deleting webhook: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

# Vault and Document Management
@mcp.tool()
async def get_recordings(recording_type: str, project_id: Optional[str] = None,
                         status: str = "active", sort: str = "created_at",
                         direction: str = "desc",
                         query: Optional[str] = None,
                         compact: bool = False) -> Dict[str, Any]:
    """List every recording of one supported type in a project or account.

    Args:
        recording_type: Comment, Document, Message, Question::Answer,
            Schedule::Entry, Todo, Todolist, Upload, or Vault
        project_id: Optional project ID. Omit to search all accessible projects.
        status: active, archived, or trashed
        sort: created_at or updated_at
        direction: desc or asc
        query: Optional case-insensitive text filter across returned metadata
        compact: Return only routing, asset, dimension, and query-context fields
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        recordings = await _run_sync(
            client.get_recordings,
            recording_type,
            project_id,
            status,
            sort,
            direction,
        )
        if query:
            normalized_query = query.casefold()
            recordings = [
                recording for recording in recordings
                if normalized_query in json.dumps(recording, ensure_ascii=False).casefold()
            ]
        if compact:
            recordings = [
                compact_recording(recording, query=query)
                for recording in recordings
            ]
        return {
            "status": "success",
            "recordings": recordings,
            "count": len(recordings)
        }
    except Exception as e:
        logger.error(f"Error getting recordings: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def trash_recording(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Move any Basecamp recording to the trash."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.trash_recording, project_id, recording_id)
        return {"status": "success", "message": "Recording trashed successfully"}
    except Exception as e:
        logger.error(f"Error trashing recording {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def archive_recording(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Archive any Basecamp recording."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.archive_recording, project_id, recording_id)
        return {"status": "success", "message": "Recording archived successfully"}
    except Exception as e:
        logger.error(f"Error archiving recording {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def restore_recording(project_id: str, recording_id: str) -> Dict[str, Any]:
    """Restore an archived Basecamp recording to active status."""
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        await _run_sync(client.restore_recording, project_id, recording_id)
        return {"status": "success", "message": "Recording restored successfully"}
    except Exception as e:
        logger.error(f"Error restoring recording {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def update_recording_visibility(
    recording_id: str, visible_to_clients: bool
) -> Dict[str, Any]:
    """Toggle client visibility for a Basecamp recording."""
    if not isinstance(visible_to_clients, bool):
        return _error_response("Invalid input", "visible_to_clients must be a boolean")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        recording = await _run_sync(
            client.update_recording_visibility, recording_id, visible_to_clients
        )
        return {"status": "success", "recording": recording}
    except Exception as e:
        logger.error(f"Error updating recording visibility {recording_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_vaults(project_id: str, vault_id: str) -> Dict[str, Any]:
    """List child vaults in a vault.

    Args:
        project_id: Project ID
        vault_id: Parent vault ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        vaults = await _run_sync(client.get_vaults, project_id, vault_id)
        return {
            "status": "success",
            "vaults": vaults,
            "count": len(vaults)
        }
    except Exception as e:
        logger.error(f"Error getting vaults: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_documents(project_id: str, vault_id: str) -> Dict[str, Any]:
    """List documents in a vault.

    Args:
        project_id: Project ID
        vault_id: Vault ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        docs = await _run_sync(client.get_documents, project_id, vault_id)
        return {
            "status": "success",
            "documents": docs,
            "count": len(docs)
        }
    except Exception as e:
        logger.error(f"Error getting documents: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_document(project_id: str, document_id: str) -> Dict[str, Any]:
    """Get a single document.

    Args:
        project_id: Project ID
        document_id: Document ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        doc = await _run_sync(client.get_document, project_id, document_id)
        return {
            "status": "success",
            "document": doc
        }
    except Exception as e:
        logger.error(f"Error getting document: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def create_document(project_id: str, vault_id: str, title: str, content: str,
                          publish: bool = True) -> Dict[str, Any]:
    """Create a document in a vault.

    Args:
        project_id: Project ID
        vault_id: Vault ID
        title: Document title
        content: Document HTML content
        publish: When true, publish immediately. When false, create a draft.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        doc = await _run_sync(
            client.create_document,
            project_id,
            vault_id,
            title,
            content,
            status="active" if publish else None,
        )
        return {
            "status": "success",
            "document": doc,
            "result": f"Document '{title}' {'published' if publish else 'drafted'} successfully"
        }
    except Exception as e:
        logger.error(f"Error creating document: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return _error_response(
                "OAuth token expired",
                "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again.",
            )
        return _error_response("Execution error", str(e))


@mcp.tool()
async def create_draft_document(project_id: str, vault_id: str, title: str, content: str) -> Dict[str, Any]:
    """Create a draft document in a vault without publishing it.

    Args:
        project_id: Project ID
        vault_id: Vault ID
        title: Document title
        content: Document HTML content
    """
    return await create_document(
        project_id,
        vault_id,
        title,
        content,
        publish=False,
    )

@mcp.tool()
async def update_document(project_id: str, document_id: str, title: Optional[str] = None, content: Optional[str] = None) -> Dict[str, Any]:
    """Update a document.

    Args:
        project_id: Project ID
        document_id: Document ID
        title: New title
        content: New HTML content
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        doc = await _run_sync(client.update_document, project_id, document_id, title, content)
        return {
            "status": "success",
            "document": doc
        }
    except Exception as e:
        logger.error(f"Error updating document: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def trash_document(project_id: str, document_id: str) -> Dict[str, Any]:
    """Move a document to trash.

    Args:
        project_id: Project ID
        document_id: Document ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.trash_document, project_id, document_id)
        return {
            "status": "success",
            "message": "Document trashed"
        }
    except Exception as e:
        logger.error(f"Error trashing document: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

# Upload Management
@mcp.tool()
async def get_uploads(project_id: str, vault_id: Optional[str] = None) -> Dict[str, Any]:
    """List uploads in a project or vault.

    Args:
        project_id: Project ID
        vault_id: Optional vault ID to limit to specific vault
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        uploads = await _run_sync(client.get_uploads, project_id, vault_id)
        return {
            "status": "success",
            "uploads": uploads,
            "count": len(uploads)
        }
    except Exception as e:
        logger.error(f"Error getting uploads: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def get_upload(project_id: str, upload_id: str) -> Dict[str, Any]:
    """Get details for a specific upload.

    Args:
        project_id: Project ID
        upload_id: Upload ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        upload = await _run_sync(client.get_upload, project_id, upload_id)
        return {
            "status": "success",
            "upload": upload
        }
    except Exception as e:
        logger.error(f"Error getting upload: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {
                "error": "OAuth token expired",
                "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."
            }
        return {
            "error": "Execution error",
            "message": str(e)
        }

@mcp.tool()
async def update_upload(
    upload_id: str,
    description: Optional[str] = None,
    base_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Update an upload's metadata without replacing its file."""
    if description is None and base_name is None:
        return _error_response("Invalid input", "description or base_name is required")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        upload = await _run_sync(client.update_upload, upload_id, description, base_name)
        return {"status": "success", "upload": upload, "message": "Upload updated"}
    except Exception as e:
        logger.error(f"Error updating upload {upload_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def get_upload_versions(
    upload_id: str, action: Optional[str] = None
) -> Dict[str, Any]:
    """Get raw version events for an upload, optionally filtered by action."""
    if action is not None and action not in {"created", "active", "blob_changed"}:
        return _error_response(
            "Invalid input", "action must be created, active, or blob_changed"
        )
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        versions = await _run_sync(client.get_upload_versions, upload_id, action)
        return {"status": "success", "versions": versions, "count": len(versions)}
    except Exception as e:
        logger.error(f"Error getting upload versions {upload_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def create_upload_version(
    upload_id: str,
    attachable_sgid: str,
    base_name: Optional[str] = None,
    description: Optional[str] = None,
    notify: Optional[str] = None,
    subscriptions: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Replace an upload's file while preserving its recording URL."""
    if not attachable_sgid:
        return _error_response("Invalid input", "attachable_sgid is required")
    if notify is not None and notify not in {"default", "everyone", "custom"}:
        return _error_response("Invalid input", "notify must be default, everyone, or custom")
    if notify == "custom" and not subscriptions:
        return _error_response("Invalid input", "subscriptions are required when notify is custom")
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()
    try:
        upload = await _run_sync(
            client.create_upload_version,
            upload_id,
            attachable_sgid,
            base_name,
            description,
            notify,
            subscriptions,
        )
        return {"status": "success", "upload": upload, "message": "Upload version created"}
    except Exception as e:
        logger.error(f"Error creating upload version {upload_id}: {e}")
        return _error_response("Execution error", str(e))

@mcp.tool()
async def download_upload(
    project_id: str,
    upload_id: str,
    max_bytes: int = 25_000_000,
) -> Any:
    """Download the binary content of an upload (PDF, image, document, ...).

    Returns MCP content blocks: a text summary plus the file itself as an
    embedded resource (or ImageContent for image MIME types). The MCP host
    forwards the blob to the model, so Claude reads PDFs natively (tables,
    images, OCR).

    Host compatibility: the file is only readable if the MCP host forwards
    `ImageContent` / `EmbeddedResource` (`BlobResourceContents`) to the
    model. Claude Code (CLI) supports both, including `application/pdf`.
    Claude Desktop / claude.ai web currently rejects non-image
    `EmbeddedResource` blocks ("Resources of type 'application/pdf' are
    not currently supported"); the bytes arrive at the host but never
    reach the model.

    Args:
        project_id: Project ID
        upload_id: Upload ID
        max_bytes: Reject files larger than this (default 25 MB). Very large
            payloads stress the MCP transport and the model context.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        result = await _run_sync(
            client.download_upload, project_id, upload_id, max_bytes
        )
    except Exception as e:
        return _handle_download_error(e, "upload")

    filename = result["filename"] or f"upload-{upload_id}"
    data = result["data"]
    content_type = result["content_type"]
    return _serialize_blob_for_mcp(
        data=data,
        content_type=content_type,
        filename=filename,
        summary=(
            f"Downloaded '{filename}' ({content_type}, {len(data)} bytes) "
            f"from upload {upload_id} in project {project_id}."
        ),
        resource_uri=(
            f"basecamp://buckets/{project_id}/uploads/{upload_id}/{filename}"
        ),
    )

@mcp.tool()
async def download_attachment(
    project_id: str,
    download_url: str,
    max_bytes: int = 25_000_000,
    expected_byte_size: Optional[int] = None,
) -> Any:
    """Download an inline comment/message attachment as MCP content.

    Use this for files embedded into a comment or message body — the entries
    found in ``content_attachments[]`` on comments, messages, etc. Pass the
    entry's ``download_url`` verbatim.

    For files that are their own ``Upload`` recording in a vault ("Docs &
    Files"), use ``download_upload`` instead. Inline attachments are
    ``Attachment`` objects with their own IDs and cannot be resolved through
    the uploads endpoint.

    Returns MCP content blocks: a text summary plus the file itself as
    ImageContent (for ``image/*`` MIME types) or an EmbeddedResource
    (BlobResourceContents) for everything else.

    Host compatibility: the file is only readable if the MCP host forwards
    ``ImageContent`` / ``EmbeddedResource`` (``BlobResourceContents``) to
    the model. Claude Code (CLI) supports both, including
    ``application/pdf``. Claude Desktop / claude.ai web currently rejects
    non-image ``EmbeddedResource`` blocks ("Resources of type
    'application/pdf' are not currently supported"); the bytes arrive at
    the host but never reach the model.

    Args:
        project_id: Project (bucket) ID — used for the resource URI and logs.
        download_url: ``content_attachments[].download_url`` from the API
            (must point to ``*.basecampapi.com``).
        max_bytes: Reject files larger than this (default 25 MB).
        expected_byte_size: Optional advertised ``byte_size`` from the same
            ``content_attachments[]`` entry. When provided, lets the server
            reject oversized files before issuing the download.
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        result = await _run_sync(
            client.download_attachment,
            download_url,
            max_bytes,
            expected_byte_size,
        )
    except Exception as e:
        return _handle_download_error(e, "attachment")

    filename = result["filename"] or "attachment"
    data = result["data"]
    content_type = result["content_type"]
    return _serialize_blob_for_mcp(
        data=data,
        content_type=content_type,
        filename=filename,
        summary=(
            f"Downloaded '{filename}' ({content_type}, {len(data)} bytes) "
            f"from inline attachment in project {project_id}."
        ),
        resource_uri=(
            f"basecamp://buckets/{project_id}/attachments/{filename}"
        ),
    )

@mcp.tool()
async def get_todolist(project_id: str, todolist_id: str) -> Dict[str, Any]:
    """Get a specific todo list by ID.

    Args:
        project_id: The project ID
        todolist_id: The todo list ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        todolist = await _run_sync(client.get_todolist, project_id, todolist_id)
        return {"status": "success", "todolist": todolist}
    except Exception as e:
        logger.error(f"Error getting todolist {todolist_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def create_todolist(
    project_id: str,
    name: str,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new todo list in a project.

    Args:
        project_id: The project ID
        name: Todo list name
        description: Optional HTML description
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        todolist = await _run_sync(
            lambda: client.create_todolist(project_id, name, description)
        )
        return {"status": "success", "todolist": todolist}
    except Exception as e:
        logger.error(f"Error creating todolist: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def update_todolist(
    project_id: str,
    todolist_id: str,
    name: str,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Update an existing todo list.

    The Basecamp API requires the name even when only updating the description.

    Args:
        project_id: The project ID
        todolist_id: The todo list ID
        name: Todo list name (required)
        description: Optional HTML description
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        todolist = await _run_sync(
            lambda: client.update_todolist(project_id, todolist_id, name, description)
        )
        return {"status": "success", "todolist": todolist}
    except Exception as e:
        logger.error(f"Error updating todolist {todolist_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def trash_todolist(project_id: str, todolist_id: str) -> Dict[str, Any]:
    """Move a todo list to the trash.

    Trashed lists can be recovered from the Basecamp web UI within 30 days.

    Args:
        project_id: The project ID
        todolist_id: The todo list ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        await _run_sync(client.trash_todolist, project_id, todolist_id)
        return {"status": "success", "message": f"Todolist {todolist_id} moved to trash"}
    except Exception as e:
        logger.error(f"Error trashing todolist {todolist_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def get_todolist_groups(project_id: str, todolist_id: str) -> Dict[str, Any]:
    """Get all groups in a todo list.

    Groups are named sections within a todo list (e.g. "Phase 1", "Backlog").

    Args:
        project_id: The project ID
        todolist_id: The todo list ID
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        groups = await _run_sync(client.get_todolist_groups, project_id, todolist_id)
        return {"status": "success", "groups": groups, "count": len(groups)}
    except Exception as e:
        logger.error(f"Error getting todolist groups: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def create_todolist_group(
    project_id: str,
    todolist_id: str,
    name: str,
    color: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new group inside a todo list.

    Groups act as named sections to organise todos within a list.

    Args:
        project_id: The project ID
        todolist_id: The todo list ID
        name: Group name
        color: Optional color – one of: white, red, orange, yellow, green,
               blue, aqua, purple, gray, pink, brown
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    try:
        group = await _run_sync(
            lambda: client.create_todolist_group(project_id, todolist_id, name, color)
        )
        return {"status": "success", "group": group}
    except Exception as e:
        logger.error(f"Error creating todolist group: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


@mcp.tool()
async def reposition_todolist_group(
    project_id: str, group_id: str, position: int
) -> Dict[str, Any]:
    """Reposition a todo list group to a new location within its list.

    Args:
        project_id: The project ID
        group_id: The group ID
        position: New 1-based position
    """
    client = _get_basecamp_client()
    if not client:
        return _get_auth_error_response()

    if position < 1:
        return {"error": "Invalid input", "message": "position must be >= 1"}

    try:
        await _run_sync(
            lambda: client.reposition_todolist_group(project_id, group_id, position)
        )
        return {"status": "success", "message": f"Group {group_id} repositioned to position {position}"}
    except Exception as e:
        logger.error(f"Error repositioning todolist group {group_id}: {e}")
        if "401" in str(e) and "expired" in str(e).lower():
            return {"error": "OAuth token expired", "message": "Your Basecamp OAuth token expired during the API call. Please re-authenticate by visiting http://localhost:8000 and completing the OAuth flow again."}
        return {"error": "Execution error", "message": str(e)}


# 🎉 COMPLETE FastMCP server with ALL tools migrated!

if __name__ == "__main__":
    logger.info("Starting Basecamp FastMCP server")
    # Run using official MCP stdio transport
    mcp.run(transport='stdio')
