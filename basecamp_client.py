import os
import re
import mimetypes
from urllib.parse import unquote, urljoin, urlparse

import requests
from dotenv import load_dotenv


# Keep API calls bounded so an unavailable Basecamp endpoint cannot hang an
# MCP request indefinitely. Downloads use the same connect timeout with a
# longer read timeout because they may carry large files.
DEFAULT_REQUEST_TIMEOUT = (10, 300)
CALENDAR_COLORS = {
    "white", "red", "orange", "yellow", "green", "blue", "aqua",
    "purple", "gray", "pink", "brown",
}


def _is_basecamp_api_host(host):
    """True only for ``basecampapi.com`` and its subdomains (dot-boundary).

    A bare suffix match would accept attacker-controlled look-alike hosts
    like ``evilbasecampapi.com``; requiring an exact match or a dot-prefixed
    subdomain keeps the OAuth Bearer token from leaking off-platform.
    """
    return host == "basecampapi.com" or host.endswith(".basecampapi.com")


def _read_capped_body(response, max_bytes, kind):
    """Stream ``response`` into bytes, enforcing ``max_bytes``.

    Checks the ``Content-Length`` header up front and applies a streaming
    cutoff during the body read, so the cap holds even when upstream metadata
    is missing or lies. ``kind`` (e.g. ``"Upload"``) is interpolated into the
    error messages. Closes ``response`` before raising. Returns
    ``(data_bytes, total_bytes)``.
    """
    content_length = response.headers.get("Content-Length")
    if max_bytes is not None and content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > max_bytes:
            response.close()
            raise Exception(
                f"{kind} size {declared_length} bytes exceeds "
                f"max_bytes={max_bytes}."
            )

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            response.close()
            raise Exception(
                f"{kind} exceeds max_bytes={max_bytes} during streaming "
                f"(downloaded {total} bytes before cutoff)."
            )
        chunks.append(chunk)
    return b"".join(chunks), total


class BasecampClient:
    """
    Client for interacting with Basecamp 3 API using Basic Authentication or OAuth 2.0.
    """

    def __init__(self, username=None, password=None, account_id=None, user_agent=None,
                 access_token=None, auth_mode="basic"):
        """
        Initialize the Basecamp client with credentials.

        Args:
            username (str, optional): Basecamp username (email) for Basic Auth
            password (str, optional): Basecamp password for Basic Auth
            account_id (str, optional): Basecamp account ID
            user_agent (str, optional): User agent for API requests
            access_token (str, optional): OAuth access token for OAuth Auth
            auth_mode (str, optional): Authentication mode ('basic' or 'oauth')
        """
        # Load environment variables if not provided directly
        load_dotenv()

        self.auth_mode = auth_mode.lower()
        self.account_id = account_id or os.getenv('BASECAMP_ACCOUNT_ID')
        self.user_agent = user_agent or os.getenv('USER_AGENT')

        # Set up authentication based on mode
        if self.auth_mode == 'basic':
            self.username = username or os.getenv('BASECAMP_USERNAME')
            self.password = password or os.getenv('BASECAMP_PASSWORD')

            if not all([self.username, self.password, self.account_id, self.user_agent]):
                raise ValueError("Missing required credentials for Basic Auth. Set them in .env file or pass them to the constructor.")

            self.auth = (self.username, self.password)
            self.headers = {
                "User-Agent": self.user_agent,
                "Content-Type": "application/json"
            }

        elif self.auth_mode == 'oauth':
            self.access_token = access_token or os.getenv('BASECAMP_ACCESS_TOKEN')

            if not all([self.access_token, self.account_id, self.user_agent]):
                raise ValueError("Missing required credentials for OAuth. Set them in .env file or pass them to the constructor.")

            self.auth = None  # No basic auth needed for OAuth
            self.headers = {
                "User-Agent": self.user_agent,
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.access_token}"
            }

        else:
            raise ValueError("Invalid auth_mode. Must be 'basic' or 'oauth'")

        # Basecamp 3 uses a different URL structure
        self.base_url = f"https://3.basecampapi.com/{self.account_id}"

    def test_connection(self):
        """Test the connection to Basecamp API."""
        response = self.get('projects.json')
        if response.status_code == 200:
            return True, "Connection successful"
        else:
            return False, f"Connection failed: {response.status_code} - {response.text}"

    def get(self, endpoint, params=None):
        """Make a GET request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.get(
            url,
            auth=self.auth,
            headers=self.headers,
            params=params,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    def _get_paginated_collection(self, endpoint, params=None, limit=None, page=None):
        """Return a Basecamp collection, following RFC 5988 ``Link`` pages."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        if page is not None and page < 1:
            raise ValueError("page must be >= 1")
        request_params = dict(params or {})
        if page is not None:
            request_params["page"] = page
        response = self.get(endpoint, params=request_params or None)
        items = []

        while True:
            if response.status_code != 200:
                raise Exception(
                    f"Failed to get collection: {response.status_code} - {response.text}"
                )

            payload = response.json()
            if not isinstance(payload, list):
                raise Exception(
                    f"Failed to get collection: expected a list, got {type(payload).__name__}"
                )
            items.extend(payload)
            if page is not None:
                return items if limit is None else items[:limit]
            if limit is not None and len(items) >= limit:
                return items[:limit]
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return items

            next_url_parts = urlparse(next_url)
            if (
                next_url_parts.scheme != "https"
                or not _is_basecamp_api_host(next_url_parts.hostname or "")
            ):
                raise Exception("Refusing to follow pagination link outside Basecamp API")

            response = requests.get(
                next_url,
                auth=self.auth,
                headers=self.headers,
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )

    def post(self, endpoint, data=None):
        """Make a POST request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.post(
            url,
            auth=self.auth,
            headers=self.headers,
            json=data,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    def put(self, endpoint, data=None):
        """Make a PUT request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.put(
            url,
            auth=self.auth,
            headers=self.headers,
            json=data,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    def delete(self, endpoint):
        """Make a DELETE request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.delete(
            url,
            auth=self.auth,
            headers=self.headers,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    def patch(self, endpoint, data=None):
        """Make a PATCH request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.patch(
            url,
            auth=self.auth,
            headers=self.headers,
            json=data,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )

    # Project methods
    def get_projects(self):
        """Get all projects."""
        return self._get_paginated_collection("projects.json")

    def get_project(self, project_id):
        """Get a specific project by ID."""
        response = self.get(f'projects/{project_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get project: {response.status_code} - {response.text}")

    def get_dock_tool(self, tool_id):
        """Get one project dock tool."""
        response = self.get(f"dock/tools/{tool_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get dock tool: {response.status_code} - {response.text}")

    def create_dock_tool(self, project_id, tool_type, title=None, visible_to_clients=None):
        """Add a tool to a project's dock."""
        valid_types = {
            "Message::Board", "Todoset", "Vault", "Schedule", "Chat::Transcript",
            "Kanban::Board", "Questionnaire", "Inbox",
        }
        if tool_type not in valid_types:
            raise ValueError("unsupported dock tool type")
        if visible_to_clients is not None and not isinstance(visible_to_clients, bool):
            raise ValueError("visible_to_clients must be a boolean")
        data = {"tool_type": tool_type}
        if title is not None:
            data["title"] = title
        if visible_to_clients is not None:
            data["visible_to_clients"] = visible_to_clients
        response = self.post(f"buckets/{project_id}/dock/tools.json", data)
        if response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to create dock tool: {response.status_code} - {response.text}")

    def update_dock_tool(self, tool_id, title):
        """Rename a project dock tool."""
        if not title or not title.strip():
            raise ValueError("title is required")
        response = self.put(f"dock/tools/{tool_id}.json", {"title": title})
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update dock tool: {response.status_code} - {response.text}")

    def enable_dock_tool(self, project_id, recording_id):
        """Enable a recording in a project's dock."""
        response = self.post(
            f"buckets/{project_id}/recordings/{recording_id}/position.json"
        )
        if response.status_code == 201:
            return True
        raise Exception(f"Failed to enable dock tool: {response.status_code} - {response.text}")

    def reposition_dock_tool(self, project_id, recording_id, position):
        """Move a dock tool to a one-based position."""
        if isinstance(position, bool) or not isinstance(position, int) or position < 1:
            raise ValueError("position must be a positive integer")
        response = self.put(
            f"buckets/{project_id}/recordings/{recording_id}/position.json",
            {"position": position},
        )
        if response.status_code == 200:
            return True
        raise Exception(f"Failed to reposition dock tool: {response.status_code} - {response.text}")

    def disable_dock_tool(self, project_id, recording_id):
        """Hide a recording from a project's dock without deleting it."""
        response = self.delete(
            f"buckets/{project_id}/recordings/{recording_id}/position.json"
        )
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to disable dock tool: {response.status_code} - {response.text}")

    def trash_dock_tool(self, tool_id):
        """Permanently delete a dock tool and its content."""
        response = self.delete(f"dock/tools/{tool_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to trash dock tool: {response.status_code} - {response.text}")

    def create_project(self, name, description=None, admissions=None):
        """Create a project."""
        data = {"name": name}
        if description is not None:
            data["description"] = description
        if admissions is not None:
            data["admissions"] = admissions
        response = self.post("projects.json", data)
        if response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to create project: {response.status_code} - {response.text}")

    def update_project(
        self,
        project_id,
        name,
        description=None,
        admissions=None,
        start_date=None,
        end_date=None,
    ):
        """Update a project's name, description, access policy, or dates."""
        data = {"name": name}
        if description is not None:
            data["description"] = description
        if admissions is not None:
            data["admissions"] = admissions
        if start_date is not None or end_date is not None:
            if start_date is None or end_date is None:
                raise ValueError("start_date and end_date must be provided together")
            data["schedule_attributes"] = {
                "start_date": start_date,
                "end_date": end_date,
            }
        response = self.put(f"projects/{project_id}.json", data)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update project: {response.status_code} - {response.text}")

    def trash_project(self, project_id):
        """Move a project to the trash."""
        response = self.delete(f"projects/{project_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to trash project: {response.status_code} - {response.text}")

    # Template methods
    def get_templates(self, status="active"):
        """Get all visible project templates in a status."""
        if status not in {"active", "archived", "trashed"}:
            raise ValueError("status must be active, archived, or trashed")
        params = {"status": status} if status != "active" else None
        return self._get_paginated_collection("templates.json", params=params)

    def get_template(self, template_id):
        """Get a project template."""
        response = self.get(f"templates/{template_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get template: {response.status_code} - {response.text}")

    def create_template(self, name, description=None):
        """Create a project template."""
        data = {"name": name}
        if description is not None:
            data["description"] = description
        response = self.post("templates.json", data)
        if response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to create template: {response.status_code} - {response.text}")

    def update_template(self, template_id, name=None, description=None):
        """Update a project template."""
        if name is None:
            name = self.get_template(template_id).get("name")
        if not name:
            raise ValueError("name is required when the template has no current name")
        data = {"name": name}
        if description is not None:
            data["description"] = description
        response = self.put(f"templates/{template_id}.json", data)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update template: {response.status_code} - {response.text}")

    def trash_template(self, template_id):
        """Move a project template to the trash."""
        response = self.delete(f"templates/{template_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to trash template: {response.status_code} - {response.text}")

    def create_project_from_template(self, template_id, project_name, project_description=None):
        """Start constructing a project from a template."""
        project = {"name": project_name}
        if project_description is not None:
            project["description"] = project_description
        response = self.post(
            f"templates/{template_id}/project_constructions.json",
            {"project": project},
        )
        if response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to construct project: {response.status_code} - {response.text}")

    def get_project_construction(self, template_id, construction_id):
        """Get the status of a project construction."""
        response = self.get(
            f"templates/{template_id}/project_constructions/{construction_id}.json"
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get project construction: {response.status_code} - {response.text}")

    # To-do list methods
    def get_todoset(self, project_id):
        """Get the todoset for a project (Basecamp 3 has one todoset per project)."""
        project = self.get_project(project_id)
        try:
            return next(_ for _ in project["dock"] if _["name"] == "todoset")
        except (IndexError, TypeError, StopIteration):
            raise Exception(
                f"Failed to get todoset for project: {project_id}. "
                f"Project response: {project}"
            )
    
    def get_todolists(self, project_id):
        """Get all todolists for a project."""
        # First get the todoset ID for this project
        todoset = self.get_todoset(project_id)
        todoset_id = todoset['id']

        # Then get all todolists in this todoset
        response = self.get(f'buckets/{project_id}/todosets/{todoset_id}/todolists.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get todolists: {response.status_code} - {response.text}")

    def get_todolist(self, project_id, todolist_id):
        """Get a specific todolist."""
        response = self.get(f'buckets/{project_id}/todolists/{todolist_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get todolist: {response.status_code} - {response.text}")

    def create_todolist(self, project_id, name, description=None):
        """Create a new todolist in a project.

        Args:
            project_id (str): Project ID
            name (str): Todolist name (required)
            description (str, optional): HTML description

        Returns:
            dict: The created todolist object
        """
        todoset = self.get_todoset(project_id)
        todoset_id = todoset['id']
        endpoint = f'buckets/{project_id}/todosets/{todoset_id}/todolists.json'
        data = {'name': name}
        if description is not None:
            data['description'] = description
        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create todolist: {response.status_code} - {response.text}")

    def update_todolist(self, project_id, todolist_id, name, description=None):
        """Update an existing todolist.

        Args:
            project_id (str): Project ID
            todolist_id (str): Todolist ID
            name (str): New name (required by API)
            description (str, optional): New HTML description

        Returns:
            dict: The updated todolist object
        """
        endpoint = f'buckets/{project_id}/todolists/{todolist_id}.json'
        data = {'name': name}
        if description is not None:
            data['description'] = description
        response = self.put(endpoint, data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update todolist: {response.status_code} - {response.text}")

    def trash_todolist(self, project_id, todolist_id):
        """Move a todolist to the trash.

        Args:
            project_id (str): Project ID
            todolist_id (str): Todolist ID

        Returns:
            bool: True if successful
        """
        endpoint = f'buckets/{project_id}/recordings/{todolist_id}/status/trashed.json'
        response = self.put(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to trash todolist: {response.status_code} - {response.text}")

    # To-do methods
    def get_todos(self, project_id, todolist_id):
        """Get all todos in a todolist, handling pagination.

        Basecamp paginates list endpoints (commonly 15 items per page). This
        implementation follows pagination via the `page` query parameter and
        the HTTP `Link` header if present, aggregating all pages before
        returning the combined list.
        """
        endpoint = f'buckets/{project_id}/todolists/{todolist_id}/todos.json'

        all_todos = []
        page = 1

        while True:
            response = self.get(endpoint, params={"page": page})
            if response.status_code != 200:
                raise Exception(f"Failed to get todos: {response.status_code} - {response.text}")

            page_items = response.json() or []
            all_todos.extend(page_items)

            # Check for next page using Link header or by empty result
            link_header = response.headers.get("Link", "")
            has_next = 'rel="next"' in link_header if link_header else False

            if not page_items or not has_next:
                break

            page += 1

        return all_todos

    def get_todo(self, project_id, todo_id):
        """Get a specific todo.

        Args:
            project_id (str): Project ID (bucket)
            todo_id (str): Todo ID

        Returns:
            dict: The todo object
        """
        endpoint = f'buckets/{project_id}/todos/{todo_id}.json'
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get todo: {response.status_code} - {response.text}")

    def create_todo(self, project_id, todolist_id, content, description=None, assignee_ids=None,
                    completion_subscriber_ids=None, notify=False, due_on=None, starts_on=None):
        """
        Create a new todo item in a todolist.
        
        Args:
            project_id (str): Project ID
            todolist_id (str): Todolist ID
            content (str): The todo item's text (required)
            description (str, optional): HTML description
            assignee_ids (list, optional): List of person IDs to assign
            completion_subscriber_ids (list, optional): List of person IDs to notify on completion
            notify (bool, optional): Whether to notify assignees
            due_on (str, optional): Due date in YYYY-MM-DD format
            starts_on (str, optional): Start date in YYYY-MM-DD format
            
        Returns:
            dict: The created todo
        """
        endpoint = f'buckets/{project_id}/todolists/{todolist_id}/todos.json'
        data = {'content': content}
        
        if description is not None:
            data['description'] = description
        if assignee_ids is not None:
            data['assignee_ids'] = assignee_ids
        if completion_subscriber_ids is not None:
            data['completion_subscriber_ids'] = completion_subscriber_ids
        if notify is not None:
            data['notify'] = notify
        if due_on is not None:
            data['due_on'] = due_on
        if starts_on is not None:
            data['starts_on'] = starts_on
            
        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create todo: {response.status_code} - {response.text}")

    def update_todo(self, project_id, todo_id, content=None, description=None, assignee_ids=None,
                    completion_subscriber_ids=None, notify=None, due_on=None, starts_on=None):
        """
        Update an existing todo item.
        
        Args:
            project_id (str): Project ID
            todo_id (str): Todo ID
            content (str, optional): The todo item's text
            description (str, optional): HTML description
            assignee_ids (list, optional): List of person IDs to assign
            completion_subscriber_ids (list, optional): List of person IDs to notify on completion
            notify (bool, optional): Whether to notify assignees
            due_on (str, optional): Due date in YYYY-MM-DD format
            starts_on (str, optional): Start date in YYYY-MM-DD format
            
        Returns:
            dict: The updated todo
        """
        endpoint = f'buckets/{project_id}/todos/{todo_id}.json'
        data = {}
        
        if content is not None:
            data['content'] = content
        if description is not None:
            data['description'] = description
        if assignee_ids is not None:
            data['assignee_ids'] = assignee_ids
        if completion_subscriber_ids is not None:
            data['completion_subscriber_ids'] = completion_subscriber_ids
        if notify is not None:
            data['notify'] = notify
        if due_on is not None:
            data['due_on'] = due_on
        if starts_on is not None:
            data['starts_on'] = starts_on

        if not data:
            raise ValueError("No fields provided to update")
            
        response = self.put(endpoint, data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update todo: {response.status_code} - {response.text}")

    def delete_todo(self, project_id, todo_id):
        """
        Move a todo item to the trash.

        Args:
            project_id (str): Project ID
            todo_id (str): Todo ID

        Returns:
            bool: True if successful
        """
        endpoint = f'buckets/{project_id}/recordings/{todo_id}/status/trashed.json'
        response = self.put(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to trash todo: {response.status_code} - {response.text}")

    def archive_todo(self, project_id, todo_id):
        """
        Archive a todo item.

        Args:
            project_id (str): Project ID
            todo_id (str): Todo ID

        Returns:
            bool: True if successful
        """
        endpoint = f'buckets/{project_id}/recordings/{todo_id}/status/archived.json'
        response = self.put(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to archive todo: {response.status_code} - {response.text}")

    def reposition_todo(self, project_id, todo_id, position, parent_id=None):
        """
        Reposition a todo within its list, or move it to another list/group.

        Args:
            project_id (str): Project ID
            todo_id (str): Todo ID
            position (int): New 1-based position
            parent_id (str, optional): ID of the target todolist or group to
                move the todo into. Omit to keep the todo in its current list.

        Returns:
            bool: True if successful
        """
        endpoint = f'buckets/{project_id}/todos/{todo_id}/position.json'
        data = {'position': position}
        if parent_id is not None:
            data['parent_id'] = parent_id
        response = self.put(endpoint, data)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to reposition todo: {response.status_code} - {response.text}")

    def complete_todo(self, project_id, todo_id):
        """
        Mark a todo as complete.
        
        Args:
            project_id (str): Project ID
            todo_id (str): Todo ID
            
        Returns:
            dict: Completion details
        """
        endpoint = f'buckets/{project_id}/todos/{todo_id}/completion.json'
        response = self.post(endpoint)
        # Basecamp returns 204 No Content on success (sometimes 201 with a body).
        if response.status_code in (200, 201, 204):
            if response.status_code == 204 or not response.text.strip():
                return {"status": "completed", "todo_id": todo_id}
            return response.json()
        else:
            raise Exception(f"Failed to complete todo: {response.status_code} - {response.text}")

    def uncomplete_todo(self, project_id, todo_id):
        """
        Mark a todo as incomplete.
        
        Args:
            project_id (str): Project ID
            todo_id (str): Todo ID
            
        Returns:
            bool: True if successful
        """
        endpoint = f'buckets/{project_id}/todos/{todo_id}/completion.json'
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to uncomplete todo: {response.status_code} - {response.text}")

    # Todolist group methods
    def get_todolist_groups(self, project_id, todolist_id):
        """Get all groups in a todolist.

        Args:
            project_id (str): Project ID
            todolist_id (str): Todolist ID

        Returns:
            list: List of group objects
        """
        endpoint = f'buckets/{project_id}/todolists/{todolist_id}/groups.json'
        all_groups = []
        page = 1
        while True:
            response = self.get(endpoint, params={"page": page})
            if response.status_code != 200:
                raise Exception(f"Failed to get todolist groups: {response.status_code} - {response.text}")
            page_items = response.json() or []
            all_groups.extend(page_items)
            link_header = response.headers.get("Link", "")
            if not page_items or 'rel="next"' not in link_header:
                break
            page += 1
        return all_groups

    def create_todolist_group(self, project_id, todolist_id, name, color=None):
        """Create a new group inside a todolist.

        Args:
            project_id (str): Project ID
            todolist_id (str): Todolist ID
            name (str): Group name (required)
            color (str, optional): One of: white, red, orange, yellow, green,
                blue, aqua, purple, gray, pink, brown

        Returns:
            dict: The created group object
        """
        endpoint = f'buckets/{project_id}/todolists/{todolist_id}/groups.json'
        data = {'name': name}
        if color is not None:
            data['color'] = color
        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create todolist group: {response.status_code} - {response.text}")

    def reposition_todolist_group(self, project_id, group_id, position):
        """Reposition a todolist group.

        Args:
            project_id (str): Project ID
            group_id (str): Group ID
            position (int): New 1-based position

        Returns:
            bool: True if successful
        """
        endpoint = f'buckets/{project_id}/todolists/groups/{group_id}/position.json'
        response = self.put(endpoint, {'position': position})
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to reposition todolist group: {response.status_code} - {response.text}")

    # People methods
    def get_people(self):
        """Get all people in the account."""
        return self._get_paginated_collection("people.json")

    def get_project_people(self, project_id):
        """Get active people on a project."""
        response = self.get(f"projects/{project_id}/people.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get project people: {response.status_code} - {response.text}")

    def update_project_people(self, project_id, grant=None, revoke=None, create=None):
        """Grant, revoke, or create people on a project."""
        data = {}
        if grant:
            data["grant"] = grant
        if revoke:
            data["revoke"] = revoke
        if create:
            data["create"] = create
        if not data:
            raise ValueError("At least one of grant, revoke, or create is required")
        response = self.put(f"projects/{project_id}/people/users.json", data)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update project people: {response.status_code} - {response.text}")

    def get_pingable_people(self):
        """Get account members who can be pinged."""
        response = self.get("circles/people.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get pingable people: {response.status_code} - {response.text}")

    def get_person(self, person_id):
        """Get one person's profile."""
        response = self.get(f"people/{person_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get person: {response.status_code} - {response.text}")

    def get_my_profile(self):
        """Get the authenticated person's profile."""
        response = self.get("my/profile.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get profile: {response.status_code} - {response.text}")

    # Account-wide work report methods
    def get_my_assignments(self):
        """Get the current user's active assignments grouped by priority."""
        response = self.get("my/assignments.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get assignments: {response.status_code} - {response.text}")

    def get_completed_assignments(self):
        """Get the current user's completed assignments."""
        response = self.get("my/assignments/completed.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get completed assignments: {response.status_code} - {response.text}")

    def get_due_assignments(self, scope="overdue"):
        """Get the current user's assignments by due-date scope."""
        valid_scopes = {
            "overdue", "due_today", "due_tomorrow", "due_later_this_week",
            "due_next_week", "due_later",
        }
        if scope not in valid_scopes:
            raise ValueError(f"scope must be one of: {', '.join(sorted(valid_scopes))}")
        response = self.get("my/assignments/due.json", params={"scope": scope})
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get due assignments: {response.status_code} - {response.text}")

    def get_overdue_todos(self):
        """Get overdue to-dos across all projects, grouped by lateness."""
        response = self.get("reports/todos/overdue.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get overdue todos: {response.status_code} - {response.text}")

    def get_upcoming_schedule(self, window_starts_on, window_ends_on):
        """Get upcoming schedule entries and due assignables across projects."""
        response = self.get(
            "reports/schedules/upcoming.json",
            params={
                "window_starts_on": window_starts_on,
                "window_ends_on": window_ends_on,
            },
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get upcoming schedule: {response.status_code} - {response.text}")

    def get_account(self):
        """Get the account associated with the current access token."""
        response = self.get("account.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get account: {response.status_code} - {response.text}")

    def update_account_name(self, name):
        """Rename the current Basecamp account."""
        if not name or not name.strip():
            raise ValueError("name is required")
        response = self.put("account/name.json", {"name": name})
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to update account name: {response.status_code} - {response.text}"
        )

    def update_account_logo(self, file_path):
        """Upload or replace the account logo (administrator/owner only)."""
        allowed_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".heic"}
        extension = os.path.splitext(file_path)[1].lower()
        if extension not in allowed_extensions:
            raise ValueError("logo must be PNG, JPEG, GIF, WebP, AVIF, or HEIC")
        file_size = os.path.getsize(file_path)
        if file_size > 5 * 1024 * 1024:
            raise ValueError("logo must not exceed 5 MB")
        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        headers = self.headers.copy()
        headers.pop("Content-Type", None)
        with open(file_path, "rb") as logo:
            response = requests.put(
                f"{self.base_url}/account/logo.json",
                auth=self.auth,
                headers=headers,
                files={"logo": (os.path.basename(file_path), logo, content_type)},
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )
        if response.status_code == 204:
            return True
        raise Exception(
            f"Failed to update account logo: {response.status_code} - {response.text}"
        )

    def remove_account_logo(self):
        """Remove the account logo (administrator/owner only)."""
        response = self.delete("account/logo.json")
        if response.status_code == 204:
            return True
        raise Exception(
            f"Failed to remove account logo: {response.status_code} - {response.text}"
        )

    def _get_everything_collection(self, endpoint, limit=100, params=None, page=None):
        """Fetch one account-wide Everything collection with a safe result cap."""
        query = dict(params or {})
        return self._get_paginated_collection(
            endpoint, params=query or None, limit=limit, page=page
        )

    def get_everything_messages(self, limit=100, page=None):
        """Get recent messages across all accessible projects."""
        return self._get_everything_collection("messages.json", limit=limit, page=page)

    def get_everything_comments(self, limit=100, page=None):
        """Get recent comments across all accessible projects."""
        return self._get_everything_collection("comments.json", limit=limit, page=page)

    def get_everything_checkins(self, limit=100, page=None):
        """Get automatic check-in answers across all accessible projects."""
        return self._get_everything_collection("checkins.json", limit=limit, page=page)

    def get_everything_forwards(self, limit=100, page=None):
        """Get inbox forwards across all accessible projects."""
        return self._get_everything_collection("forwards.json", limit=limit, page=page)

    def get_everything_files(self, limit=100, kind="all", person_ids=None, page=None):
        """Get files across all accessible projects with optional filters."""
        valid_kinds = {"all", "images", "pdfs", "documents", "videos"}
        if kind not in valid_kinds:
            raise ValueError(f"kind must be one of: {', '.join(sorted(valid_kinds))}")
        params = {}
        if kind != "all":
            params["kind"] = kind
        if person_ids:
            params["people_ids[]"] = person_ids
        return self._get_everything_collection(
            "files.json", limit=limit, params=params, page=page
        )

    def get_everything_todos(self, status="open", limit=100, assignee_ids=None, due=None, page=None):
        """Get filtered to-dos across all accessible projects."""
        endpoints = {
            "open": "todos/open.json",
            "completed": "todos/completed.json",
            "unassigned": "todos/unassigned.json",
            "no_due_date": "todos/no_due_date.json",
            "overdue": "todos/overdue.json",
        }
        if status not in endpoints:
            raise ValueError(f"status must be one of: {', '.join(endpoints)}")
        params = self._everything_task_params(assignee_ids, due)
        return self._get_everything_collection(
            endpoints[status], limit=limit, params=params, page=page
        )

    def get_everything_cards(self, status="open", limit=100, assignee_ids=None, due=None, page=None):
        """Get filtered cards across all accessible projects."""
        endpoints = {
            "open": "cards/open.json",
            "completed": "cards/completed.json",
            "unassigned": "cards/unassigned.json",
            "no_due_date": "cards/no_due_date.json",
            "not_now": "cards/not_now.json",
            "overdue": "cards/overdue.json",
        }
        if status not in endpoints:
            raise ValueError(f"status must be one of: {', '.join(endpoints)}")
        params = self._everything_task_params(assignee_ids, due)
        return self._get_everything_collection(
            endpoints[status], limit=limit, params=params, page=page
        )

    def get_timeline(self, limit=100, page=None):
        """Get recent activity across all accessible projects."""
        return self._get_everything_collection(
            "reports/progress.json", limit=limit, page=page
        )

    def get_project_timeline(self, project_id, limit=100, page=None):
        """Get recent activity within one project."""
        return self._get_everything_collection(
            f"projects/{project_id}/timeline.json", limit=limit, page=page
        )

    def get_person_timeline(self, person_id, limit=100, page=None):
        """Get timeline events created by one person."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        if page is not None and page < 1:
            raise ValueError("page must be >= 1")
        response = self.get(
            f"reports/users/progress/{person_id}.json",
            params={"page": page} if page is not None else None,
        )
        if response.status_code != 200:
            raise Exception(
                f"Failed to get person timeline: {response.status_code} - {response.text}"
            )
        result = response.json()
        events = result.get("events", [])
        if page is not None:
            result["events"] = events if limit is None else events[:limit]
            return result
        while True:
            if limit is not None and len(events) >= limit:
                result["events"] = events[:limit]
                return result
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                result["events"] = events
                return result
            next_url_parts = urlparse(next_url)
            if (
                next_url_parts.scheme != "https"
                or not _is_basecamp_api_host(next_url_parts.hostname or "")
            ):
                raise Exception("Refusing to follow pagination link outside Basecamp API")
            response = requests.get(
                next_url,
                auth=self.auth,
                headers=self.headers,
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )
            if response.status_code != 200:
                raise Exception(
                    f"Failed to get person timeline: {response.status_code} - {response.text}"
                )
            page = response.json()
            events.extend(page.get("events", []))

    def get_timesheet_report(
        self, start_date=None, end_date=None, person_id=None, bucket_id=None
    ):
        """Get the non-paginated account-wide timesheet report."""
        if (start_date is None) != (end_date is None):
            raise ValueError("start_date and end_date must be provided together")
        params = {}
        if start_date is not None:
            params["start_date"] = start_date
            params["end_date"] = end_date
        if person_id is not None:
            params["person_id"] = person_id
        if bucket_id is not None:
            params["bucket_id"] = bucket_id
        response = self.get("reports/timesheet.json", params=params or None)
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to get timesheet report: {response.status_code} - {response.text}"
        )

    def get_project_timesheet(self, project_id, limit=None, page=None):
        """Get paginated timesheet entries for a project."""
        return self._get_paginated_collection(
            f"projects/{project_id}/timesheet.json", limit=limit, page=page
        )

    def get_recording_timesheet(self, recording_id, limit=None, page=None):
        """Get paginated timesheet entries for a recording."""
        return self._get_paginated_collection(
            f"recordings/{recording_id}/timesheet.json", limit=limit, page=page
        )

    def get_timesheet_entry(self, entry_id):
        """Get one timesheet entry."""
        response = self.get(f"timesheet_entries/{entry_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to get timesheet entry: {response.status_code} - {response.text}"
        )

    def create_timesheet_entry(
        self, recording_id, date, hours, description=None, person_id=None
    ):
        """Log time against a timesheetable recording."""
        if not date:
            raise ValueError("date is required")
        if hours is None or hours == "":
            raise ValueError("hours is required")
        data = {"date": date, "hours": hours}
        if description is not None:
            data["description"] = description
        if person_id is not None:
            data["person_id"] = person_id
        response = self.post(
            f"recordings/{recording_id}/timesheet/entries.json", data
        )
        if response.status_code == 201:
            return response.json()
        raise Exception(
            f"Failed to create timesheet entry: {response.status_code} - {response.text}"
        )

    def update_timesheet_entry(
        self, entry_id, date=None, hours=None, description=None, person_id=None
    ):
        """Update selected fields on a timesheet entry."""
        data = {}
        if date is not None:
            data["date"] = date
        if hours is not None:
            data["hours"] = hours
        if description is not None:
            data["description"] = description
        if person_id is not None:
            data["person_id"] = person_id
        if not data:
            raise ValueError("at least one timesheet field is required")
        response = self.put(f"timesheet_entries/{entry_id}.json", data)
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to update timesheet entry: {response.status_code} - {response.text}"
        )

    def delete_timesheet_entry(self, entry_id):
        """Permanently delete a timesheet entry."""
        response = self.delete(f"timesheet_entries/{entry_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(
            f"Failed to delete timesheet entry: {response.status_code} - {response.text}"
        )

    def get_gauges(self, bucket_ids=None, limit=None, page=None):
        """List account-wide project gauges, optionally in a requested order."""
        params = None
        if bucket_ids:
            if isinstance(bucket_ids, (list, tuple)):
                bucket_ids = ",".join(str(bucket_id) for bucket_id in bucket_ids)
            params = {"bucket_ids": bucket_ids}
        return self._get_paginated_collection(
            "reports/gauges.json", params=params, limit=limit, page=page
        )

    def get_gauge_needles(self, project_id, limit=None, page=None):
        """Get a project's gauge history, newest first."""
        return self._get_paginated_collection(
            f"projects/{project_id}/gauge/needles.json", limit=limit, page=page
        )

    def get_gauge_needle(self, needle_id):
        """Get one gauge needle."""
        response = self.get(f"gauge_needles/{needle_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to get gauge needle: {response.status_code} - {response.text}"
        )

    def create_gauge_needle(
        self,
        project_id,
        position,
        color=None,
        description=None,
        notify=None,
        subscriptions=None,
    ):
        """Record a new project progress update."""
        self._validate_gauge_position(position)
        if color is not None and color not in {"green", "yellow", "red"}:
            raise ValueError("color must be green, yellow, or red")
        if notify is not None and notify not in {"default", "everyone", "custom"}:
            raise ValueError("notify must be default, everyone, or custom")
        if notify == "custom" and not subscriptions:
            raise ValueError("subscriptions are required when notify is custom")
        data = {"gauge_needle": {"position": position}}
        if color is not None:
            data["gauge_needle"]["color"] = color
        if description is not None:
            data["gauge_needle"]["description"] = description
        if notify is not None:
            data["notify"] = notify
        if subscriptions is not None:
            data["subscriptions"] = subscriptions
        response = self.post(f"projects/{project_id}/gauge/needles.json", data)
        if response.status_code == 201:
            return response.json()
        raise Exception(
            f"Failed to create gauge needle: {response.status_code} - {response.text}"
        )

    def update_gauge_needle(self, needle_id, description):
        """Update the description of a gauge needle."""
        if description is None:
            raise ValueError("description is required")
        response = self.put(
            f"gauge_needles/{needle_id}.json",
            {"gauge_needle": {"description": description}},
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to update gauge needle: {response.status_code} - {response.text}"
        )

    def delete_gauge_needle(self, needle_id):
        """Permanently delete a gauge needle."""
        response = self.delete(f"gauge_needles/{needle_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(
            f"Failed to delete gauge needle: {response.status_code} - {response.text}"
        )

    def toggle_gauge(self, project_id, enabled):
        """Enable or disable a project's gauge."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        response = self.put(
            f"projects/{project_id}/gauge.json", {"gauge": {"enabled": enabled}}
        )
        if response.status_code == 200:
            return True
        raise Exception(
            f"Failed to toggle gauge: {response.status_code} - {response.text}"
        )

    @staticmethod
    def _validate_gauge_position(position):
        if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position <= 100:
            raise ValueError("position must be an integer between 0 and 100")

    def get_hill_chart(self, todoset_id):
        """Get the hill chart for a to-do set."""
        response = self.get(f"todosets/{todoset_id}/hill.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to get hill chart: {response.status_code} - {response.text}"
        )

    def get_project_hill_chart(self, project_id):
        """Resolve a project's to-do set and return its hill chart."""
        project = self.get_project(project_id)
        todoset = next(
            (tool for tool in project.get("dock", []) if tool.get("name") == "todoset"),
            None,
        )
        if not todoset or not todoset.get("id"):
            raise Exception(f"Project {project_id} does not expose a todoset")
        return self.get_hill_chart(todoset["id"])

    def update_hill_chart_settings(self, todoset_id, tracked=None, untracked=None):
        """Track or untrack to-do lists on a hill chart."""
        if not tracked and not untracked:
            raise ValueError("tracked or untracked is required")
        data = {}
        if tracked:
            data["tracked"] = tracked
        if untracked:
            data["untracked"] = untracked
        response = self.put(f"todosets/{todoset_id}/hills/settings.json", data)
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to update hill chart settings: {response.status_code} - {response.text}"
        )

    def create_question(self, questionnaire_id, title, schedule, visible_to_clients=None):
        """Create an automatic check-in question."""
        if not title:
            raise ValueError("title is required")
        if not isinstance(schedule, dict) or not schedule:
            raise ValueError("schedule must be a non-empty object")
        data = {"question": {"title": title, "schedule": schedule}}
        if visible_to_clients is not None:
            if not isinstance(visible_to_clients, bool):
                raise ValueError("visible_to_clients must be a boolean")
            data["visible_to_clients"] = visible_to_clients
        response = self.post(f"questionnaires/{questionnaire_id}/questions.json", data)
        if response.status_code == 201:
            return response.json()
        raise Exception(
            f"Failed to create question: {response.status_code} - {response.text}"
        )

    def update_question(self, question_id, title=None, schedule=None):
        """Update selected fields on an automatic check-in question."""
        question = {}
        if title is not None:
            if not title:
                raise ValueError("title must not be empty")
            question["title"] = title
        if schedule is not None:
            if not isinstance(schedule, dict) or not schedule:
                raise ValueError("schedule must be a non-empty object")
            question["schedule"] = schedule
        if not question:
            raise ValueError("title or schedule is required")
        response = self.put(f"questions/{question_id}.json", {"question": question})
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to update question: {response.status_code} - {response.text}"
        )

    def pause_question(self, question_id):
        """Pause an automatic check-in question."""
        response = self.post(f"questions/{question_id}/pause.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to pause question: {response.status_code} - {response.text}"
        )

    def resume_question(self, question_id):
        """Resume an automatic check-in question."""
        response = self.delete(f"questions/{question_id}/pause.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to resume question: {response.status_code} - {response.text}"
        )

    def update_question_notification_settings(
        self, question_id, notify_on_answer=None, digest_include_unanswered=None
    ):
        """Update the authenticated user's question notification settings."""
        if notify_on_answer is None and digest_include_unanswered is None:
            raise ValueError(
                "notify_on_answer or digest_include_unanswered is required"
            )
        data = {}
        for name, value in (
            ("notify_on_answer", notify_on_answer),
            ("digest_include_unanswered", digest_include_unanswered),
        ):
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError(f"{name} must be a boolean")
                data[name] = value
        response = self.put(
            f"questions/{question_id}/notification_settings.json", data
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(
            "Failed to update question notification settings: "
            f"{response.status_code} - {response.text}"
        )

    def get_question_answerers(self, question_id, limit=None):
        """List people who have answered a question."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        return self._get_paginated_collection(
            f"questions/{question_id}/answers/by.json", limit=limit
        )

    def get_lineup_markers(self):
        """List account-wide Lineup markers."""
        return self._get_paginated_collection("lineup/markers.json")

    def create_lineup_marker(self, name, date):
        """Create an account-wide Lineup marker."""
        if not name:
            raise ValueError("name is required")
        if not date:
            raise ValueError("date is required")
        response = self.post("lineup/markers.json", {"name": name, "date": date})
        if response.status_code == 201:
            return True
        raise Exception(f"Failed to create Lineup marker: {response.status_code} - {response.text}")

    def update_lineup_marker(self, marker_id, name=None, date=None):
        """Update fields on an account-wide Lineup marker."""
        data = {}
        if name is not None:
            data["name"] = name
        if date is not None:
            data["date"] = date
        if not data:
            raise ValueError("name or date is required")
        response = self.put(f"lineup/markers/{marker_id}.json", data)
        if response.status_code == 200:
            return True
        raise Exception(f"Failed to update Lineup marker: {response.status_code} - {response.text}")

    def delete_lineup_marker(self, marker_id):
        """Delete an account-wide Lineup marker."""
        response = self.delete(f"lineup/markers/{marker_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to delete Lineup marker: {response.status_code} - {response.text}")

    @staticmethod
    def _everything_task_params(assignee_ids=None, due=None):
        """Build the documented Everything task filter query."""
        if due is not None and due not in {"with", "without", "overdue"}:
            raise ValueError("due must be one of: with, without, overdue")
        params = {}
        if assignee_ids:
            params["assignee_ids[]"] = assignee_ids
        if due:
            params["due"] = due
        return params

    def get_question_reminders(self, limit=None):
        """Get pending automatic check-in reminders for the current user."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        reminders = self._get_paginated_collection("my/question_reminders.json", limit=limit)
        return reminders if limit is None else reminders[:limit]

    def get_my_bookmarks(self, limit=None):
        """Get the authenticated user's bookmarked recordings."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        return self._get_paginated_collection("my/bookmarks.json", limit=limit)

    def get_bookmark_status(self, recording_id):
        """Get whether a recording is bookmarked by the current user."""
        response = self.get(f"recordings/{recording_id}/bookmark.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get bookmark status: {response.status_code} - {response.text}")

    def create_bookmark(self, recording_id):
        """Bookmark a recording for the current user."""
        response = self.post(f"recordings/{recording_id}/bookmark.json")
        if response.status_code == 201:
            return True
        raise Exception(f"Failed to create bookmark: {response.status_code} - {response.text}")

    def delete_bookmark(self, recording_id):
        """Remove a recording from the current user's bookmarks."""
        response = self.delete(f"recordings/{recording_id}/bookmark.json")
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to delete bookmark: {response.status_code} - {response.text}")

    def get_my_drafts(self, limit=None):
        """Get the authenticated user's unpublished Basecamp drafts."""
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        return self._get_paginated_collection("my/drafts.json", limit=limit)

    def get_my_note(self):
        """Get the authenticated user's personal note."""
        response = self.get("my/notes.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get personal note: {response.status_code} - {response.text}")

    def update_my_note(self, content):
        """Replace the authenticated user's personal note content."""
        response = self.put("my/notes.json", {"note": {"content": content}})
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update personal note: {response.status_code} - {response.text}")

    def get_calendar(self, calendar_id):
        """Get a Basecamp calendar by ID."""
        response = self.get(f"calendars/{calendar_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get calendar: {response.status_code} - {response.text}")

    def update_calendar(self, calendar_id, color):
        """Update a Basecamp calendar's display color."""
        if color not in CALENDAR_COLORS:
            raise ValueError(f"color must be one of: {', '.join(sorted(CALENDAR_COLORS))}")
        response = self.put(f"calendars/{calendar_id}.json", {"calendar": {"color": color}})
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update calendar: {response.status_code} - {response.text}")

    def get_notifications(self, page=None, limit_bubble_ups=False):
        """Get the current user's grouped notification inbox."""
        params = {}
        if page is not None:
            if page < 1:
                raise ValueError("page must be >= 1")
            params["page"] = page
        if limit_bubble_ups:
            params["limit_bubble_ups"] = True
        response = self.get("my/readings.json", params=params or None)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get notifications: {response.status_code} - {response.text}")

    def get_bubble_ups(self):
        """Get all current and scheduled bubble-ups."""
        return self._get_paginated_collection("my/readings/bubble_ups.json")

    def mark_notifications_read(self, readables):
        """Mark notification readable SGIDs as read."""
        if not readables:
            raise ValueError("readables must contain at least one readable SGID")
        response = self.put("my/unreads.json", {"readables": readables})
        if response.status_code == 200:
            return True
        raise Exception(f"Failed to mark notifications read: {response.status_code} - {response.text}")

    def get_subscription(self, project_id, recording_id):
        """Get subscribers and current-user subscription state for a recording."""
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/subscription.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get subscription: {response.status_code} - {response.text}")

    def subscribe_to_recording(self, project_id, recording_id):
        """Subscribe the current user to a recording."""
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/subscription.json"
        response = self.post(endpoint)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to subscribe to recording: {response.status_code} - {response.text}")

    def unsubscribe_from_recording(self, project_id, recording_id):
        """Unsubscribe the current user from a recording."""
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/subscription.json"
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to unsubscribe from recording: {response.status_code} - {response.text}")

    def update_subscription(self, project_id, recording_id, subscriptions=None, unsubscriptions=None):
        """Add and/or remove people from a recording's subscriber list."""
        data = {}
        if subscriptions:
            data["subscriptions"] = subscriptions
        if unsubscriptions:
            data["unsubscriptions"] = unsubscriptions
        if not data:
            raise ValueError("subscriptions or unsubscriptions is required")
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/subscription.json"
        response = self.put(endpoint, data)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update subscription: {response.status_code} - {response.text}")

    def prioritize_assignment(self, recording_id):
        """Add an assignment recording to the current user's Up Next list."""
        response = self.post("my/priorities.json", {"id": recording_id})
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to prioritize assignment: {response.status_code} - {response.text}")

    def deprioritize_assignment(self, recording_id):
        """Remove an assignment recording from the current user's Up Next list."""
        response = self.delete(f"my/priorities/{recording_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to deprioritize assignment: {response.status_code} - {response.text}")

    def reorder_priority(self, recording_id, position):
        """Move an assignment recording to a position in Up Next."""
        if position < 1:
            raise ValueError("position must be >= 1")
        response = self.post(
            "my/priority_moves.json",
            {"source_id": recording_id, "position": position},
        )
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to reorder priority: {response.status_code} - {response.text}")

    # Campfire (chat) methods
    def get_campfires(self, project_id):
        """Get the Campfire rooms enabled in a project."""
        project = self.get_project(project_id)
        campfires = []
        for item in project.get("dock", []):
            if item.get("name") != "chat":
                continue
            response = self.get(f"buckets/{project_id}/chats/{item['id']}.json")
            if response.status_code != 200:
                raise Exception(f"Failed to get campfire: {response.status_code} - {response.text}")
            campfires.append(response.json())
        return campfires

    def get_campfire_lines(self, project_id, campfire_id):
        """Get all chat lines from a campfire, following pagination."""
        return self._get_paginated_collection(
            f'buckets/{project_id}/chats/{campfire_id}/lines.json'
        )

    def get_campfire_line(self, project_id, campfire_id, line_id):
        """Get one line from a campfire."""
        response = self.get(
            f'buckets/{project_id}/chats/{campfire_id}/lines/{line_id}.json'
        )
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get campfire line: {response.status_code} - {response.text}")

    def create_campfire_line(self, project_id, campfire_id, content):
        """Create a plain-text line in a campfire."""
        endpoint = f'buckets/{project_id}/chats/{campfire_id}/lines.json'
        response = self.post(endpoint, {"content": content})
        if response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to create campfire line: {response.status_code} - {response.text}")

    def delete_campfire_line(self, project_id, campfire_id, line_id):
        """Permanently delete a campfire line."""
        endpoint = f'buckets/{project_id}/chats/{campfire_id}/lines/{line_id}.json'
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to delete campfire line: {response.status_code} - {response.text}")

    # Message board methods
    def get_message_board(self, project_id):
        """Get the message board for a project.

        The message board ID is discovered from the project's dock array,
        following the same pattern as get_todoset().

        Args:
            project_id: Project/bucket ID

        Returns:
            dict: Message board details including id, title, messages_count, etc.
        """
        project = self.get_project(project_id)
        try:
            dock_item = next(_ for _ in project["dock"] if _["name"] == "message_board")
            board_id = dock_item['id']
            response = self.get(f'buckets/{project_id}/message_boards/{board_id}.json')
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Failed to get message board: {response.status_code} - {response.text}")
        except (IndexError, TypeError, StopIteration):
            raise Exception(f"No message board found for project: {project_id}")

    def get_messages(self, project_id, message_board_id=None):
        """Get all messages from a message board, handling pagination.

        Basecamp paginates list endpoints (commonly 15 items per page). This
        implementation follows pagination via the `page` query parameter and
        the HTTP `Link` header if present, aggregating all pages before
        returning the combined list.

        Args:
            project_id: Project/bucket ID
            message_board_id: Optional message board ID. If not provided,
                will be discovered from the project's dock.

        Returns:
            list: All messages from the message board
        """
        if not message_board_id:
            message_board = self.get_message_board(project_id)
            message_board_id = message_board['id']

        endpoint = f'buckets/{project_id}/message_boards/{message_board_id}/messages.json'

        all_messages = []
        page = 1

        while True:
            response = self.get(endpoint, params={"page": page})
            if response.status_code != 200:
                raise Exception(f"Failed to get messages: {response.status_code} - {response.text}")

            page_items = response.json() or []
            all_messages.extend(page_items)

            # Check for next page using Link header
            link_header = response.headers.get("Link", "")
            has_next = 'rel="next"' in link_header if link_header else False

            if not page_items or not has_next:
                break

            page += 1

        return all_messages

    def get_message(self, project_id, message_id):
        """Get a specific message.

        Args:
            project_id: Project/bucket ID
            message_id: Message ID

        Returns:
            dict: Message details including title, content, creator, etc.
        """
        endpoint = f'buckets/{project_id}/messages/{message_id}.json'
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get message: {response.status_code} - {response.text}")

    def get_message_categories(self, project_id):
        """Get message categories (types) for a project.

        Args:
            project_id: Project/bucket ID

        Returns:
            list: Message categories with id, name, and icon
        """
        endpoint = f'buckets/{project_id}/categories.json'
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get message categories: {response.status_code} - {response.text}")

    def get_message_category(self, project_id, category_id):
        """Get one message type/category."""
        response = self.get(f"buckets/{project_id}/categories/{category_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get message category: {response.status_code} - {response.text}")

    def create_message_category(self, project_id, name, icon):
        """Create a message type/category."""
        response = self.post(
            f"buckets/{project_id}/categories.json",
            {"name": name, "icon": icon},
        )
        if response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to create message category: {response.status_code} - {response.text}")

    def update_message_category(self, project_id, category_id, name, icon):
        """Update a message type/category."""
        response = self.put(
            f"buckets/{project_id}/categories/{category_id}.json",
            {"name": name, "icon": icon},
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update message category: {response.status_code} - {response.text}")

    def delete_message_category(self, project_id, category_id):
        """Delete a message type/category."""
        response = self.delete(f"buckets/{project_id}/categories/{category_id}.json")
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to delete message category: {response.status_code} - {response.text}")

    def create_message(self, project_id, subject, content, message_board_id=None, category_id=None, status="active"):
        """Create a new message on a project's message board.

        Args:
            project_id: Project/bucket ID
            subject: Message title/subject
            content: Message body in HTML format
            message_board_id: Optional message board ID (auto-discovered if not provided)
            category_id: Optional message type/category ID
            status: Optional message status. Set to "active" to publish immediately;
                pass None to create a draft.

        Returns:
            dict: Created message details
        """
        if not message_board_id:
            message_board = self.get_message_board(project_id)
            message_board_id = message_board['id']

        endpoint = f'buckets/{project_id}/message_boards/{message_board_id}/messages.json'
        data = {'subject': subject, 'content': content}
        if status is not None:
            data['status'] = status
        if category_id is not None:
            data['category_id'] = category_id

        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create message: {response.status_code} - {response.text}")

    def update_message(self, project_id, message_id, subject=None, content=None,
                       category_id=None):
        """Update one or more fields on a message."""
        data = {}
        if subject is not None:
            data["subject"] = subject
        if content is not None:
            data["content"] = content
        if category_id is not None:
            data["category_id"] = category_id
        if not data:
            raise ValueError("At least one message field must be provided")

        endpoint = f"buckets/{project_id}/messages/{message_id}.json"
        response = self.put(endpoint, data)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update message: {response.status_code} - {response.text}")

    def pin_message(self, project_id, message_id):
        """Pin a message to the top of its message board."""
        endpoint = f"buckets/{project_id}/recordings/{message_id}/pin.json"
        response = self.post(endpoint)
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to pin message: {response.status_code} - {response.text}")

    def unpin_message(self, project_id, message_id):
        """Remove a message from the top of its message board."""
        endpoint = f"buckets/{project_id}/recordings/{message_id}/pin.json"
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to unpin message: {response.status_code} - {response.text}")

    # Inbox methods (Email Forwards)
    def get_inbox(self, project_id):
        """Get the inbox for a project (email forwards container).

        The inbox ID is discovered from the project's dock array,
        following the same pattern as get_message_board().

        Args:
            project_id: Project/bucket ID

        Returns:
            dict: Inbox details including forwards_count, forwards_url, etc.
        """
        project = self.get_project(project_id)
        try:
            dock_item = next(_ for _ in project["dock"] if _["name"] == "inbox")
            inbox_id = dock_item['id']
            response = self.get(f'buckets/{project_id}/inboxes/{inbox_id}.json')
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(f"Failed to get inbox: {response.status_code} - {response.text}")
        except (IndexError, TypeError, StopIteration):
            raise Exception(f"No inbox found for project: {project_id}")

    def get_forwards(self, project_id, inbox_id=None):
        """Get all forwards from an inbox, handling pagination.

        Args:
            project_id: Project/bucket ID
            inbox_id: Optional inbox ID. If not provided,
                will be discovered from the project's dock.

        Returns:
            list: All forwards from the inbox
        """
        if not inbox_id:
            inbox = self.get_inbox(project_id)
            inbox_id = inbox['id']

        endpoint = f'buckets/{project_id}/inboxes/{inbox_id}/forwards.json'

        all_forwards = []
        page = 1

        while True:
            response = self.get(endpoint, params={"page": page})
            if response.status_code != 200:
                raise Exception(f"Failed to get forwards: {response.status_code} - {response.text}")

            page_items = response.json() or []
            all_forwards.extend(page_items)

            # Check for next page using Link header
            link_header = response.headers.get("Link", "")
            has_next = 'rel="next"' in link_header if link_header else False

            if not page_items or not has_next:
                break

            page += 1

        return all_forwards

    def get_forward(self, project_id, forward_id):
        """Get a specific forward.

        Args:
            project_id: Project/bucket ID
            forward_id: Forward ID

        Returns:
            dict: Forward details including content, subject, from, replies_count, etc.
        """
        endpoint = f'buckets/{project_id}/inbox_forwards/{forward_id}.json'
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get forward: {response.status_code} - {response.text}")

    def get_inbox_replies(self, project_id, forward_id):
        """Get all replies to a forward, handling pagination.

        Args:
            project_id: Project/bucket ID
            forward_id: Forward ID

        Returns:
            list: All replies to the forward
        """
        endpoint = f'buckets/{project_id}/inbox_forwards/{forward_id}/replies.json'

        all_replies = []
        page = 1

        while True:
            response = self.get(endpoint, params={"page": page})
            if response.status_code != 200:
                raise Exception(f"Failed to get inbox replies: {response.status_code} - {response.text}")

            page_items = response.json() or []
            all_replies.extend(page_items)

            # Check for next page using Link header
            link_header = response.headers.get("Link", "")
            has_next = 'rel="next"' in link_header if link_header else False

            if not page_items or not has_next:
                break

            page += 1

        return all_replies

    def get_inbox_reply(self, project_id, forward_id, reply_id):
        """Get a specific inbox reply.

        Args:
            project_id: Project/bucket ID
            forward_id: Forward ID
            reply_id: Reply ID

        Returns:
            dict: Reply details including content, creator, etc.
        """
        endpoint = f'buckets/{project_id}/inbox_forwards/{forward_id}/replies/{reply_id}.json'
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get inbox reply: {response.status_code} - {response.text}")

    def trash_forward(self, project_id, forward_id):
        """Trash a forward.

        Uses the generic recordings trash endpoint, same pattern as trash_document.

        Args:
            project_id: Project/bucket ID
            forward_id: Forward ID

        Returns:
            bool: True if successful
        """
        endpoint = f"buckets/{project_id}/recordings/{forward_id}/status/trashed.json"
        response = self.put(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to trash forward: {response.status_code} - {response.text}")

    # Schedule methods
    def get_schedule(self, project_id):
        """Get the schedule resource discovered from the project dock."""
        project = self.get_project(project_id)
        try:
            schedule_item = next(
                item for item in project["dock"] if item["name"] == "schedule"
            )
        except (IndexError, TypeError, StopIteration):
            raise Exception(f"No schedule found for project: {project_id}")

        response = self.get(
            f'buckets/{project_id}/schedules/{schedule_item["id"]}.json'
        )
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get schedule: {response.status_code} - {response.text}")

    def get_schedule_entries(self, project_id):
        """
        Get schedule entries for a project.

        Args:
            project_id (int): Project ID

        Returns:
            list: Schedule entries
        """
        try:
            schedule = self.get_schedule(project_id)
            schedule_id = schedule["id"]
            entries_endpoint = (
                f"buckets/{project_id}/schedules/{schedule_id}/entries.json"
            )
            return self._get_paginated_collection(entries_endpoint)
        except Exception as e:
            raise Exception(f"Failed to get schedule entries: {str(e)}")

    def get_schedule_entry(self, project_id, entry_id):
        """Get one schedule entry by ID."""
        response = self.get(f"buckets/{project_id}/schedule_entries/{entry_id}.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get schedule entry: {response.status_code} - {response.text}")

    def get_schedule_entry_occurrence(self, project_id, entry_id, date):
        """Get one occurrence of a recurring schedule entry."""
        response = self.get(
            f"buckets/{project_id}/schedule_entries/{entry_id}/occurrences/{date}.json"
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to get schedule entry occurrence: {response.status_code} - {response.text}"
        )

    def create_schedule_entry(
        self,
        project_id,
        summary,
        starts_at,
        ends_at,
        description=None,
        participant_ids=None,
        all_day=None,
        notify=None,
    ):
        """Create a schedule entry under the project's schedule."""
        schedule = self.get_schedule(project_id)
        data = {
            "summary": summary,
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
        for key, value in (
            ("description", description),
            ("participant_ids", participant_ids),
            ("all_day", all_day),
            ("notify", notify),
        ):
            if value is not None:
                data[key] = value

        response = self.post(
            f"buckets/{project_id}/schedules/{schedule['id']}/entries.json",
            data,
        )
        if response.status_code == 201:
            return response.json()
        raise Exception(f"Failed to create schedule entry: {response.status_code} - {response.text}")

    def update_schedule_entry(
        self,
        project_id,
        entry_id,
        summary=None,
        starts_at=None,
        ends_at=None,
        description=None,
        participant_ids=None,
        all_day=None,
        notify=None,
    ):
        """Update fields on an existing schedule entry."""
        data = {}
        for key, value in (
            ("summary", summary),
            ("starts_at", starts_at),
            ("ends_at", ends_at),
            ("description", description),
            ("participant_ids", participant_ids),
            ("all_day", all_day),
            ("notify", notify),
        ):
            if value is not None:
                data[key] = value
        if not data:
            raise ValueError("at least one schedule entry field must be provided")

        response = self.put(
            f"buckets/{project_id}/schedule_entries/{entry_id}.json",
            data,
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update schedule entry: {response.status_code} - {response.text}")

    # Comments methods
    def get_comments(self, project_id, recording_id, page=1):
        """
        Get comments for a recording (todos, message, etc.).

        Args:
            project_id (int): Project/bucket ID.
            recording_id (int): ID of the recording (todos, message, etc.)
            page (int): Page number for pagination (default: 1).
                        Basecamp uses geared pagination: page 1 has 15 results,
                        page 2 has 30, page 3 has 50, page 4+ has 100.

        Returns:
            dict: Contains 'comments' list and pagination metadata:
                  - comments: list of comments
                  - total_count: total number of comments (from X-Total-Count header)
                  - next_page: next page number if available, None otherwise
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/comments.json"
        response = self.get(endpoint, params={"page": page})
        if response.status_code == 200:
            # Parse pagination headers
            total_count = response.headers.get('X-Total-Count')
            total_count = int(total_count) if total_count else None

            # Parse Link header for next page
            next_page = None
            link_header = response.headers.get('Link', '')
            # Split by comma to handle multiple links (e.g., rel="prev", rel="next")
            for link in link_header.split(','):
                if 'rel="next"' in link:
                    match = re.search(r'page=(\d+)', link)
                    if match:
                        next_page = int(match.group(1))
                    break

            return {
                "comments": response.json(),
                "total_count": total_count,
                "next_page": next_page
            }
        else:
            raise Exception(f"Failed to get comments: {response.status_code} - {response.text}")

    def create_comment(self, recording_id, bucket_id, content):
        """
        Create a comment on a recording.

        Args:
            recording_id (int): ID of the recording to comment on
            bucket_id (int): Project/bucket ID
            content (str): Content of the comment in HTML format

        Returns:
            dict: The created comment
        """
        endpoint = f"buckets/{bucket_id}/recordings/{recording_id}/comments.json"
        data = {"content": content}
        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create comment: {response.status_code} - {response.text}")

    def get_comment(self, comment_id, bucket_id):
        """
        Get a specific comment.

        Args:
            comment_id (int): Comment ID
            bucket_id (int): Project/bucket ID

        Returns:
            dict: Comment details
        """
        endpoint = f"buckets/{bucket_id}/comments/{comment_id}.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get comment: {response.status_code} - {response.text}")

    def update_comment(self, comment_id, bucket_id, content):
        """
        Update a comment.

        Args:
            comment_id (int): Comment ID
            bucket_id (int): Project/bucket ID
            content (str): New content for the comment in HTML format

        Returns:
            dict: Updated comment
        """
        endpoint = f"buckets/{bucket_id}/comments/{comment_id}.json"
        data = {"content": content}
        response = self.put(endpoint, data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update comment: {response.status_code} - {response.text}")

    def delete_comment(self, comment_id, bucket_id):
        """
        Delete a comment.

        Args:
            comment_id (int): Comment ID
            bucket_id (int): Project/bucket ID

        Returns:
            bool: True if successful
        """
        endpoint = f"buckets/{bucket_id}/comments/{comment_id}.json"
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to delete comment: {response.status_code} - {response.text}")

    def _get_questionnaire_id(self, project_id):
        """Resolve the automatic check-ins questionnaire from the project dock."""
        project = self.get_project(project_id)
        questionnaire = next(
            (item for item in project.get("dock", []) if item.get("name") == "questionnaire"),
            None,
        )
        if not questionnaire:
            raise Exception(f"No automatic check-ins questionnaire found for project: {project_id}")
        return questionnaire["id"]

    def get_questionnaire(self, project_id, questionnaire_id=None):
        """Get an automatic check-ins questionnaire."""
        questionnaire_id = questionnaire_id or self._get_questionnaire_id(project_id)
        response = self.get(f"buckets/{project_id}/questionnaires/{questionnaire_id}.json")
        if response.status_code != 200:
            raise Exception(f"Failed to get questionnaire: {response.status_code} - {response.text}")
        return response.json()

    def get_questions(self, project_id, questionnaire_id=None, page=None):
        """Get all questions in an automatic check-ins questionnaire."""
        questionnaire_id = questionnaire_id or self._get_questionnaire_id(project_id)
        endpoint = f"buckets/{project_id}/questionnaires/{questionnaire_id}/questions.json"
        if page is not None:
            response = self.get(endpoint, params={"page": page})
            if response.status_code != 200:
                raise Exception(f"Failed to get questions: {response.status_code} - {response.text}")
            return response.json()
        return self._get_paginated_collection(endpoint)

    def get_question(self, project_id, question_id):
        """Get one automatic check-in question."""
        response = self.get(f"buckets/{project_id}/questions/{question_id}.json")
        if response.status_code != 200:
            raise Exception(f"Failed to get question: {response.status_code} - {response.text}")
        return response.json()

    def get_daily_check_ins(self, project_id, page=None):
        """Compatibility alias for listing automatic check-in questions."""
        return self.get_questions(project_id, page=page)

    def get_question_answers(self, project_id, question_id, page=None):
        endpoint = f"buckets/{project_id}/questions/{question_id}/answers.json"
        if page is not None:
            response = self.get(endpoint, params={"page": page})
            if response.status_code != 200:
                raise Exception(f"Failed to get question answers: {response.status_code} - {response.text}")
            return response.json()
        return self._get_paginated_collection(endpoint)

    def get_question_answer(self, project_id, answer_id):
        """Get one automatic check-in answer."""
        response = self.get(f"buckets/{project_id}/question_answers/{answer_id}.json")
        if response.status_code != 200:
            raise Exception(f"Failed to get question answer: {response.status_code} - {response.text}")
        return response.json()

    # Card Table methods
    def get_card_tables(self, project_id):
        """Get all card tables for a project."""
        project = self.get_project(project_id)
        try:
            return [item for item in project["dock"] if item.get("name") in ("kanban_board", "card_table")]
        except (IndexError, TypeError):
            return []

    def get_card_table(self, project_id):
        """Get the first card table for a project (Basecamp 3 can have multiple card tables per project)."""
        card_tables = self.get_card_tables(project_id)
        if not card_tables:
            raise Exception(f"No card tables found for project: {project_id}")
        return card_tables[0]  # Return the first card table
    
    def get_card_table_details(self, project_id, card_table_id):
        """Get details for a specific card table."""
        response = self.get(f'buckets/{project_id}/card_tables/{card_table_id}.json')
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 204:
            # 204 means "No Content" - return an empty structure
            return {"lists": [], "id": card_table_id, "status": "empty"}
        else:
            raise Exception(f"Failed to get card table: {response.status_code} - {response.text}")

    # Card Table Column methods
    def get_columns(self, project_id, card_table_id):
        """Get all columns in a card table."""
        # Get the card table details which includes the lists (columns)
        card_table_details = self.get_card_table_details(project_id, card_table_id)
        return card_table_details.get('lists', [])

    def get_column(self, project_id, column_id):
        """Get a specific column."""
        response = self.get(f'buckets/{project_id}/card_tables/columns/{column_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get column: {response.status_code} - {response.text}")

    def create_column(self, project_id, card_table_id, title):
        """Create a new column in a card table."""
        data = {"title": title}
        response = self.post(f'buckets/{project_id}/card_tables/{card_table_id}/columns.json', data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create column: {response.status_code} - {response.text}")

    def update_column(self, project_id, column_id, title):
        """Update a column title."""
        data = {"title": title}
        response = self.put(f'buckets/{project_id}/card_tables/columns/{column_id}.json', data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update column: {response.status_code} - {response.text}")

    def move_column(self, project_id, column_id, position, card_table_id):
        """Move a column to a new position."""
        data = {
            "source_id": column_id, 
            "target_id": card_table_id,
            "position": position
        }
        response = self.post(f'buckets/{project_id}/card_tables/{card_table_id}/moves.json', data)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to move column: {response.status_code} - {response.text}")

    def update_column_color(self, project_id, column_id, color):
        """Update a column color."""
        data = {"color": color}
        response = self.patch(f'buckets/{project_id}/card_tables/columns/{column_id}/color.json', data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update column color: {response.status_code} - {response.text}")

    def put_column_on_hold(self, project_id, column_id):
        """Put a column on hold."""
        response = self.post(f'buckets/{project_id}/card_tables/columns/{column_id}/on_hold.json')
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to put column on hold: {response.status_code} - {response.text}")

    def remove_column_hold(self, project_id, column_id):
        """Remove hold from a column."""
        response = self.delete(f'buckets/{project_id}/card_tables/columns/{column_id}/on_hold.json')
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to remove column hold: {response.status_code} - {response.text}")

    def watch_column(self, project_id, column_id):
        """Subscribe to column notifications."""
        response = self.post(f'buckets/{project_id}/card_tables/lists/{column_id}/subscription.json')
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to watch column: {response.status_code} - {response.text}")

    def unwatch_column(self, project_id, column_id):
        """Unsubscribe from column notifications."""
        response = self.delete(f'buckets/{project_id}/card_tables/lists/{column_id}/subscription.json')
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to unwatch column: {response.status_code} - {response.text}")

    # Card Table Card methods
    def get_cards(self, project_id, column_id):
        """Get all cards in a column."""
        response = self.get(f'buckets/{project_id}/card_tables/lists/{column_id}/cards.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get cards: {response.status_code} - {response.text}")

    def get_card(self, project_id, card_id):
        """Get a specific card."""
        response = self.get(f'buckets/{project_id}/card_tables/cards/{card_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get card: {response.status_code} - {response.text}")

    def create_card(self, project_id, column_id, title, content=None, due_on=None, notify=False):
        """Create a new card in a column."""
        data = {"title": title}
        if content:
            data["content"] = content
        if due_on:
            data["due_on"] = due_on
        if notify:
            data["notify"] = notify
        response = self.post(f'buckets/{project_id}/card_tables/lists/{column_id}/cards.json', data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create card: {response.status_code} - {response.text}")

    def update_card(self, project_id, card_id, title=None, content=None, due_on=None, assignee_ids=None):
        """Update a card."""
        data = {}
        if title:
            data["title"] = title
        if content:
            data["content"] = content
        if due_on:
            data["due_on"] = due_on
        if assignee_ids:
            data["assignee_ids"] = assignee_ids
        response = self.put(f'buckets/{project_id}/card_tables/cards/{card_id}.json', data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update card: {response.status_code} - {response.text}")

    def move_card(self, project_id, card_id, column_id, position=None):
        """Move a card to a column or linked cross-project wormhole."""
        if position is not None:
            if isinstance(position, bool) or not isinstance(position, int) or position < 1:
                raise ValueError("position must be a positive integer")
        data = {"column_id": column_id}
        if position is not None:
            data["position"] = position
        response = self.post(f'buckets/{project_id}/card_tables/cards/{card_id}/moves.json', data)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to move card: {response.status_code} - {response.text}")

    def create_card_table_wormhole(self, project_id, card_table_id, destination_recording_id):
        """Create a wormhole to a column on another card table."""
        if not destination_recording_id:
            raise ValueError("destination_recording_id is required")
        response = self.post(
            f"buckets/{project_id}/card_tables/{card_table_id}/wormholes.json",
            {"destination_recording_id": destination_recording_id},
        )
        if response.status_code == 201:
            return response.json()
        raise Exception(
            f"Failed to create card table wormhole: {response.status_code} - {response.text}"
        )

    def update_card_table_wormhole(self, project_id, wormhole_id, destination_recording_id):
        """Change a wormhole's destination column."""
        if not destination_recording_id:
            raise ValueError("destination_recording_id is required")
        response = self.put(
            f"buckets/{project_id}/card_tables/wormholes/{wormhole_id}.json",
            {"destination_recording_id": destination_recording_id},
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to update card table wormhole: {response.status_code} - {response.text}"
        )

    def delete_card_table_wormhole(self, project_id, wormhole_id):
        """Delete a card table wormhole."""
        response = self.delete(
            f"buckets/{project_id}/card_tables/wormholes/{wormhole_id}.json"
        )
        if response.status_code == 204:
            return True
        raise Exception(
            f"Failed to delete card table wormhole: {response.status_code} - {response.text}"
        )

    def complete_card(self, project_id, card_id):
        """Mark a card as complete."""
        response = self.post(f'buckets/{project_id}/todos/{card_id}/completion.json')
        if response.status_code in (200, 201, 204):
            if response.status_code == 204 or not response.text.strip():
                return {"status": "completed", "card_id": card_id}
            return response.json()
        else:
            raise Exception(f"Failed to complete card: {response.status_code} - {response.text}")

    def uncomplete_card(self, project_id, card_id):
        """Mark a card as incomplete."""
        response = self.delete(f'buckets/{project_id}/todos/{card_id}/completion.json')
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to uncomplete card: {response.status_code} - {response.text}")

    # Card Steps methods
    def get_card_steps(self, project_id, card_id):
        """Get all steps (sub-tasks) for a card."""
        card = self.get_card(project_id, card_id)
        return card.get('steps', [])

    def create_card_step(self, project_id, card_id, title, due_on=None, assignee_ids=None):
        """Create a new step (sub-task) for a card."""
        data = {"title": title}
        if due_on:
            data["due_on"] = due_on
        if assignee_ids:
            data["assignee_ids"] = assignee_ids
        response = self.post(f'buckets/{project_id}/card_tables/cards/{card_id}/steps.json', data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create card step: {response.status_code} - {response.text}")

    def get_card_step(self, project_id, step_id):
        """Get a specific card step."""
        response = self.get(f'buckets/{project_id}/card_tables/steps/{step_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get card step: {response.status_code} - {response.text}")

    def update_card_step(self, project_id, step_id, title=None, due_on=None, assignee_ids=None):
        """Update a card step."""
        data = {}
        if title:
            data["title"] = title
        if due_on:
            data["due_on"] = due_on
        if assignee_ids:
            data["assignee_ids"] = assignee_ids
        response = self.put(f'buckets/{project_id}/card_tables/steps/{step_id}.json', data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update card step: {response.status_code} - {response.text}")

    def delete_card_step(self, project_id, step_id):
        """Delete a card step."""
        response = self.delete(f'buckets/{project_id}/card_tables/steps/{step_id}.json')
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to delete card step: {response.status_code} - {response.text}")

    def complete_card_step(self, project_id, step_id):
        """Mark a card step as complete."""
        response = self.put(
            f'buckets/{project_id}/card_tables/steps/{step_id}/completions.json',
            {"completion": "on"},
        )
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to complete card step: {response.status_code} - {response.text}")

    def uncomplete_card_step(self, project_id, step_id):
        """Mark a card step as incomplete."""
        response = self.put(
            f'buckets/{project_id}/card_tables/steps/{step_id}/completions.json',
            {"completion": "off"},
        )
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to uncomplete card step: {response.status_code} - {response.text}")

    # New methods for additional Basecamp API functionality
    def create_attachment(self, file_path, name, content_type="application/octet-stream"):
        """Upload an attachment and return the attachable sgid."""
        with open(file_path, "rb") as f:
            data = f.read()

        headers = self.headers.copy()
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(data))

        response = requests.post(
            f"{self.base_url}/attachments.json",
            auth=self.auth,
            headers=headers,
            params={"name": name},
            data=data,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create attachment: {response.status_code} - {response.text}")

    def get_events(self, project_id, recording_id):
        """Get events for a recording."""
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/events.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get events: {response.status_code} - {response.text}")

    def get_webhooks(self, project_id):
        """List webhooks for a project."""
        return self._get_paginated_collection(f"buckets/{project_id}/webhooks.json")

    def create_webhook(self, project_id, payload_url, types=None):
        """Create a webhook for a project."""
        self._validate_webhook_url(payload_url)
        data = {"payload_url": payload_url}
        if types:
            data["types"] = types
        endpoint = f"buckets/{project_id}/webhooks.json"
        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create webhook: {response.status_code} - {response.text}")

    def get_webhook(self, project_id, webhook_id):
        """Get one webhook and its recent delivery records."""
        endpoint = f"buckets/{project_id}/webhooks/{webhook_id}.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get webhook: {response.status_code} - {response.text}")

    def update_webhook(self, project_id, webhook_id, payload_url, types=None, active=None):
        """Update a webhook destination, event types, or active state."""
        self._validate_webhook_url(payload_url)
        data = {"payload_url": payload_url}
        if types is not None:
            data["types"] = types
        if active is not None:
            data["active"] = active
        endpoint = f"buckets/{project_id}/webhooks/{webhook_id}.json"
        response = self.put(endpoint, data)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to update webhook: {response.status_code} - {response.text}")

    @staticmethod
    def _validate_webhook_url(payload_url):
        parsed = urlparse(payload_url or "")
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("payload_url must be an HTTPS URL")

    def delete_webhook(self, project_id, webhook_id):
        """Delete a webhook."""
        endpoint = f"buckets/{project_id}/webhooks/{webhook_id}.json"
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to delete webhook: {response.status_code} - {response.text}")

    def get_vaults(self, project_id, vault_id):
        """List child vaults in a vault."""
        endpoint = f"buckets/{project_id}/vaults/{vault_id}/vaults.json"
        return self._get_paginated_collection(endpoint)

    def get_recordings(self, recording_type, project_id=None, status="active",
                       sort="created_at", direction="desc"):
        """List recordings of one supported type across a project or account."""
        if status not in {"active", "archived", "trashed"}:
            raise ValueError("status must be active, archived, or trashed")
        if sort not in {"created_at", "updated_at"}:
            raise ValueError("sort must be created_at or updated_at")
        if direction not in {"asc", "desc"}:
            raise ValueError("direction must be asc or desc")
        endpoint = "projects/recordings.json"
        params = {
            "type": recording_type,
            "status": status,
            "sort": sort,
            "direction": direction,
        }
        if project_id is not None:
            params["bucket"] = project_id
        return self._get_paginated_collection(endpoint, params=params)

    def get_search_metadata(self):
        """Get the account's current valid full-text search filters."""
        response = self.get("searches/metadata.json")
        if response.status_code == 200:
            return response.json()
        raise Exception(f"Failed to get search metadata: {response.status_code} - {response.text}")

    def search_recordings(
        self,
        query,
        type_names=None,
        bucket_ids=None,
        creator_ids=None,
        file_type=None,
        exclude_chat=False,
        since=None,
        sort=None,
        per_page=None,
    ):
        """Search account content through Basecamp's native Search API."""
        if not query or not query.strip():
            raise ValueError("query must not be empty")
        if per_page is not None and per_page < 1:
            raise ValueError("per_page must be >= 1")

        params = {"q": query}
        if type_names:
            params["type_names[]"] = type_names
        if bucket_ids:
            params["bucket_ids[]"] = bucket_ids
        if creator_ids:
            params["creator_ids[]"] = creator_ids
        if file_type is not None:
            params["file_type"] = file_type
        if exclude_chat:
            params["exclude_chat"] = 1
        if since is not None:
            params["since"] = since
        if sort is not None:
            params["sort"] = sort
        if per_page is not None:
            params["per_page"] = per_page
        return self._get_paginated_collection("search.json", params=params)

    def update_recording_status(self, project_id, recording_id, status):
        """Set a recording status using Basecamp's generic recording endpoint."""
        if status not in {"active", "archived", "trashed"}:
            raise ValueError("status must be active, archived, or trashed")
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/status/{status}.json"
        response = self.put(endpoint)
        if response.status_code == 204:
            return True
        raise Exception(f"Failed to set recording status: {response.status_code} - {response.text}")

    def trash_recording(self, project_id, recording_id):
        """Move a recording to the trash."""
        return self.update_recording_status(project_id, recording_id, "trashed")

    def archive_recording(self, project_id, recording_id):
        """Archive a recording."""
        return self.update_recording_status(project_id, recording_id, "archived")

    def restore_recording(self, project_id, recording_id):
        """Restore an archived recording to active status."""
        return self.update_recording_status(project_id, recording_id, "active")

    def get_documents(self, project_id, vault_id):
        """List documents in a vault."""
        endpoint = f"buckets/{project_id}/vaults/{vault_id}/documents.json"
        return self._get_paginated_collection(endpoint)

    def get_document(self, project_id, document_id):
        """Get a single document."""
        endpoint = f"buckets/{project_id}/documents/{document_id}.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get document: {response.status_code} - {response.text}")

    def create_document(self, project_id, vault_id, title, content, status="active"):
        """Create a document in a vault."""
        data = {"title": title, "content": content}
        if status is not None:
            data["status"] = status
        endpoint = f"buckets/{project_id}/vaults/{vault_id}/documents.json"
        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create document: {response.status_code} - {response.text}")

    def update_document(self, project_id, document_id, title=None, content=None):
        """Update a document's title or content."""
        data = {}
        if title:
            data["title"] = title
        if content:
            data["content"] = content
        endpoint = f"buckets/{project_id}/documents/{document_id}.json"
        response = self.put(endpoint, data)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to update document: {response.status_code} - {response.text}")

    def trash_document(self, project_id, document_id):
        """Trash a document."""
        endpoint = f"buckets/{project_id}/recordings/{document_id}/status/trashed.json"
        response = self.put(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to trash document: {response.status_code} - {response.text}")

    # Upload methods
    def get_uploads(self, project_id, vault_id=None):
        """List uploads in a project or vault."""
        if vault_id:
            endpoint = f"buckets/{project_id}/vaults/{vault_id}/uploads.json"
        else:
            endpoint = f"buckets/{project_id}/uploads.json"
        return self._get_paginated_collection(endpoint)

    def get_upload(self, project_id, upload_id):
        """Get a single upload."""
        endpoint = f"buckets/{project_id}/uploads/{upload_id}.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get upload: {response.status_code} - {response.text}")

    def update_upload(self, upload_id, description=None, base_name=None):
        """Update upload metadata using the canonical flat route."""
        data = {}
        if description is not None:
            data["description"] = description
        if base_name is not None:
            data["base_name"] = base_name
        if not data:
            raise ValueError("description or base_name is required")
        response = self.put(f"uploads/{upload_id}.json", data)
        if response.status_code == 200:
            return response.json()
        raise Exception(
            f"Failed to update upload: {response.status_code} - {response.text}"
        )

    def get_upload_versions(self, upload_id, action=None):
        """Get raw upload version events, optionally filtered by action."""
        versions = self._get_paginated_collection(f"uploads/{upload_id}/versions.json")
        if action is not None:
            valid_actions = {"created", "active", "blob_changed"}
            if action not in valid_actions:
                raise ValueError(
                    "action must be created, active, or blob_changed"
                )
            versions = [version for version in versions if version.get("action") == action]
        return versions

    def create_upload_version(
        self,
        upload_id,
        attachable_sgid,
        base_name=None,
        description=None,
        notify=None,
        subscriptions=None,
    ):
        """Replace an upload's file while preserving its recording URL."""
        if not attachable_sgid:
            raise ValueError("attachable_sgid is required")
        if notify is not None and notify not in {"default", "everyone", "custom"}:
            raise ValueError("notify must be default, everyone, or custom")
        if notify == "custom" and not subscriptions:
            raise ValueError("subscriptions are required when notify is custom")
        data = {"attachable_sgid": attachable_sgid}
        if base_name is not None:
            data["base_name"] = base_name
        if description is not None:
            data["description"] = description
        if notify is not None:
            data["notify"] = notify
        if subscriptions is not None:
            data["subscriptions"] = subscriptions
        response = self.post(f"uploads/{upload_id}/versions.json", data)
        if response.status_code == 201:
            return response.json()
        raise Exception(
            f"Failed to create upload version: {response.status_code} - {response.text}"
        )

    def update_recording_visibility(self, recording_id, visible_to_clients):
        """Toggle client visibility for a recording."""
        if not isinstance(visible_to_clients, bool):
            raise ValueError("visible_to_clients must be a boolean")
        response = self.put(
            f"recordings/{recording_id}/client_visibility.json",
            {"visible_to_clients": visible_to_clients},
        )
        if response.status_code == 200:
            return response.json()
        raise Exception(
            "Failed to update recording visibility: "
            f"{response.status_code} - {response.text}"
        )

    def download_upload(self, project_id, upload_id, max_bytes=None):
        """Download the binary content of an upload (e.g. PDF, image, doc).

        Returns dict with keys: data (bytes), filename, content_type, byte_size,
        title, app_url.

        The Basecamp API returns a `download_url` that 302-redirects to a signed
        S3 URL. `requests` strips the Authorization header on cross-domain
        redirects, so passing self.headers here is safe.
        """
        meta = self.get_upload(project_id, upload_id)
        download_url = meta.get("download_url")
        if not download_url:
            raise Exception(
                f"Upload {upload_id} has no download_url; not a downloadable file"
            )

        parsed_download_url = urlparse(download_url)
        if (
            parsed_download_url.scheme != "https"
            or not parsed_download_url.hostname
            or not _is_basecamp_api_host(parsed_download_url.hostname)
        ):
            raise Exception(
                "Refusing to download upload from non-basecampapi host: "
                f"{parsed_download_url.hostname!r}"
            )

        byte_size = meta.get("byte_size")
        if (
            max_bytes is not None
            and byte_size is not None
            and byte_size > max_bytes
        ):
            raise Exception(
                f"Upload size {byte_size} bytes exceeds max_bytes={max_bytes}. "
                f"Increase max_bytes or fetch the file via the Basecamp UI."
            )

        # `requests` strips the Authorization header automatically on the
        # cross-domain redirect to signed storage. We still sanitize the
        # JSON Content-Type (meaningless for a binary GET) so the storage
        # host doesn't reject the request, and we stream the body with the
        # same Content-Length / cutoff enforcement as download_attachment so
        # max_bytes holds even when meta.byte_size is missing or stale.
        request_headers = dict(self.headers)
        request_headers.pop("Content-Type", None)

        response = requests.get(
            download_url,
            auth=self.auth,
            headers=request_headers,
            allow_redirects=True,
            stream=True,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            body_preview = response.text[:200] if response.text else ""
            response.close()
            raise Exception(
                f"Failed to download upload: {response.status_code} - "
                f"{body_preview}"
            )

        data, total = _read_capped_body(response, max_bytes, "Upload")

        return {
            "data": data,
            "filename": meta.get("filename"),
            "content_type": (
                meta.get("content_type")
                or response.headers.get("Content-Type")
                or "application/octet-stream"
            ),
            "byte_size": meta.get("byte_size") or total,
            "title": meta.get("title"),
            "app_url": meta.get("app_url"),
        }

    # Inline-attachment methods (comment/message attachments, not vault uploads)
    def download_attachment(
        self, download_url, max_bytes=None, expected_byte_size=None
    ):
        """Download the binary content of an inline comment/message attachment.

        ``download_url`` is the per-blob URL as returned in
        ``content_attachments[].download_url`` by the comments/messages API,
        e.g. ``https://3.basecampapi.com/{account}/blobs/{key}/download/{name}``.

        The API responds with a 302 redirect to a pre-signed storage host
        (``storage.app.basecamp.com``). The OAuth Bearer token must only be
        sent to ``*.basecampapi.com``; the storage URL is already signed and
        forwarding the Authorization header there would leak the token.
        We therefore disable automatic redirects, walk the chain manually, and
        strip auth credentials on the first cross-host hop.

        Returns dict with keys: data (bytes), filename, content_type, byte_size.
        """
        if not download_url:
            raise Exception("download_url is required")

        parsed_initial = urlparse(download_url)
        if (
            parsed_initial.scheme != "https"
            or not parsed_initial.hostname
            or not _is_basecamp_api_host(parsed_initial.hostname)
        ):
            raise Exception(
                "Refusing to download from non-basecampapi host: "
                f"{parsed_initial.hostname!r}"
            )

        # Early reject when the caller passes the advertised byte_size from
        # content_attachments[]: avoids burning bandwidth for huge files.
        if (
            max_bytes is not None
            and expected_byte_size is not None
            and expected_byte_size > max_bytes
        ):
            raise Exception(
                f"Attachment size {expected_byte_size} bytes exceeds "
                f"max_bytes={max_bytes}. Increase max_bytes or fetch the file "
                f"via the Basecamp UI."
            )

        current_url = download_url
        max_hops = 5
        for _ in range(max_hops):
            host = urlparse(current_url).hostname or ""
            is_basecamp_host = _is_basecamp_api_host(host)

            request_headers = dict(self.headers)
            request_auth = self.auth
            # Storage hosts (e.g. storage.app.basecamp.com) accept only
            # pre-signed URLs and reject — or worse, log — Authorization
            # headers carrying our OAuth token. Strip on cross-host.
            if not is_basecamp_host:
                request_headers.pop("Authorization", None)
                request_auth = None
            # JSON content-type is meaningless for a binary GET; drop so the
            # storage host doesn't reject the request.
            request_headers.pop("Content-Type", None)

            response = requests.get(
                current_url,
                auth=request_auth,
                headers=request_headers,
                allow_redirects=False,
                stream=True,
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )

            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise Exception(
                        f"Attachment redirect {response.status_code} "
                        f"without Location header"
                    )
                current_url = urljoin(current_url, location)
                continue

            if response.status_code != 200:
                body_preview = response.text[:200] if response.text else ""
                response.close()
                raise Exception(
                    f"Failed to download attachment: {response.status_code} "
                    f"- {body_preview}"
                )

            data, total = _read_capped_body(response, max_bytes, "Attachment")

            content_type = (
                response.headers.get("Content-Type")
                or "application/octet-stream"
            )

            filename = None
            cd = response.headers.get("Content-Disposition")
            if cd:
                m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
                if m:
                    filename = unquote(m.group(1))
            if not filename:
                path = parsed_initial.path
                if path:
                    last = path.rsplit("/", 1)[-1]
                    filename = unquote(last) or None

            return {
                "data": data,
                "filename": filename,
                "content_type": content_type,
                "byte_size": total,
            }

        raise Exception(
            f"Too many redirects (>{max_hops}) while downloading attachment"
        )
