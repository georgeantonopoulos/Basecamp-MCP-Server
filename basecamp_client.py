import os
import re
from urllib.parse import unquote, urljoin, urlparse

import requests
from dotenv import load_dotenv


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

    # Upper bound for get_all_pages(); guards against endless pagination.
    MAX_PAGES = 1000

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
        return requests.get(url, auth=self.auth, headers=self.headers, params=params,
                            timeout=(10, 300))

    def get_all_pages(self, endpoint, params=None, error_label="items"):
        """Fetch all pages of a list endpoint, following pagination.

        Basecamp paginates list endpoints (commonly 15 items per page). This
        helper follows pagination via the `page` query parameter and the HTTP
        `Link` header, aggregating all pages before returning the combined
        list.

        Args:
            endpoint (str): API endpoint returning a JSON array
            params (dict, optional): Extra query parameters
            error_label (str): Label used in the error message on failure

        Returns:
            list: All items across all pages

        Raises:
            Exception: On a non-200 response, or if pagination exceeds
                MAX_PAGES (guards against a malformed API response that
                keeps advertising a next page forever).
        """
        all_items = []
        page = 1

        while True:
            if page > self.MAX_PAGES:
                raise Exception(
                    f"Failed to get {error_label}: pagination exceeded "
                    f"{self.MAX_PAGES} pages for endpoint {endpoint}")
            page_params = dict(params or {}, page=page)
            response = self.get(endpoint, params=page_params)
            if response.status_code != 200:
                raise Exception(f"Failed to get {error_label}: {response.status_code} - {response.text}")

            page_items = response.json() or []
            all_items.extend(page_items)

            # Check for next page using Link header or by empty result
            link_header = response.headers.get("Link", "")
            if not page_items or 'rel="next"' not in link_header:
                break

            page += 1

        return all_items

    def post(self, endpoint, data=None):
        """Make a POST request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.post(url, auth=self.auth, headers=self.headers, json=data)

    def put(self, endpoint, data=None):
        """Make a PUT request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.put(url, auth=self.auth, headers=self.headers, json=data)

    def delete(self, endpoint):
        """Make a DELETE request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.delete(url, auth=self.auth, headers=self.headers)

    def patch(self, endpoint, data=None):
        """Make a PATCH request to the Basecamp API."""
        url = f"{self.base_url}/{endpoint}"
        return requests.patch(url, auth=self.auth, headers=self.headers, json=data)

    # Project methods
    def get_projects(self):
        """Get all projects, handling pagination."""
        return self.get_all_pages('projects.json', error_label="projects")

    def get_project(self, project_id):
        """Get a specific project by ID."""
        response = self.get(f'projects/{project_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get project: {response.status_code} - {response.text}")

    def _find_dock_item(self, project, name):
        """Return a named project dock item, or None when it is unavailable."""
        try:
            dock = project["dock"]
        except (KeyError, TypeError):
            return None

        try:
            for item in dock:
                if isinstance(item, dict) and item.get("name") == name:
                    return item
        except TypeError:
            return None

        return None

    # To-do list methods
    def get_todoset(self, project_id):
        """Get the todoset for a project (Basecamp 3 has one todoset per project)."""
        project = self.get_project(project_id)
        dock_item = self._find_dock_item(project, "todoset")
        if dock_item is None:
            raise Exception(f"Failed to get todoset for project: {project_id}")
        return dock_item
    
    def get_todolists(self, project_id):
        """Get all todolists for a project."""
        # First get the todoset ID for this project
        todoset = self.get_todoset(project_id)
        todoset_id = todoset['id']

        # Then get all todolists in this todoset, handling pagination
        return self.get_all_pages(
            f'buckets/{project_id}/todosets/{todoset_id}/todolists.json',
            error_label="todolists")

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
    def get_todos(self, project_id, todolist_id, completed=None, status=None):
        """Get todos in a todolist, handling pagination.

        Basecamp paginates list endpoints (commonly 15 items per page). This
        implementation follows pagination via the `page` query parameter and
        the HTTP `Link` header if present, aggregating all pages before
        returning the combined list.

        By default the Basecamp API returns only the active (incomplete)
        to-dos. Use `completed` to fetch the completed ones instead, or
        `status` to fetch archived/trashed to-dos.
        See https://github.com/basecamp/bc3-api/blob/master/sections/todos.md.

        Args:
            project_id (str): Project ID
            todolist_id (str): Todo list ID
            completed (bool, optional): When True, return completed to-dos
                (Basecamp's `?completed=true`). When False/None the default
                active set is returned.
            status (str, optional): Recording-status filter — 'archived' or
                'trashed' (Basecamp's `?status=...`).

        Returns:
            list: All matching todos across all pages.
        """
        params = {}
        if completed:
            params['completed'] = 'true'
        if status is not None:
            if status not in ('archived', 'trashed'):
                raise ValueError(
                    "status must be 'archived' or 'trashed', got "
                    f"{status!r}")
            params['status'] = status
        return self.get_all_pages(
            f'buckets/{project_id}/todolists/{todolist_id}/todos.json',
            params=params or None,
            error_label="todos")

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
        return self.get_all_pages(
            f'buckets/{project_id}/todolists/{todolist_id}/groups.json',
            error_label="todolist groups")

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
        """Get all people in the account, handling pagination."""
        return self.get_all_pages('people.json', error_label="people")

    # Report methods
    def get_assignable_people(self):
        """Get all people who can have to-dos assigned to them.

        Wraps `GET /reports/todos/assigned.json`. Useful for building a list
        of people to then retrieve their individual to-do assignments via
        get_person_assignments().

        Returns:
            list: Person objects (id, name, email_address, title, ...)
        """
        return self.get_all_pages('reports/todos/assigned.json',
                                  error_label="assignable people")

    def get_person_assignments(self, person_id, group_by=None):
        """Get all active, pending to-dos assigned to a specific person.

        Wraps `GET /reports/todos/assigned/{person_id}.json` — the API
        counterpart of the web report at
        `/reports/todos/assigned/{person_id}`. Unlike per-project todo
        listings, this returns the person's assignments across ALL projects
        in one call.

        Args:
            person_id (str): The person's ID
            group_by (str, optional): 'bucket' groups to-dos by project,
                'date' groups by due date. API default: 'bucket'.

        Returns:
            dict: {person, grouped_by, todos} where todos spans all projects
        """
        endpoint = f'reports/todos/assigned/{person_id}.json'
        params = {'group_by': group_by} if group_by else None

        # The response is a single object, but the embedded todos list may be
        # paginated via the Link header like other list endpoints. Follow
        # `rel="next"` and merge the todos arrays defensively.
        result = None
        page = 1
        while True:
            if page > self.MAX_PAGES:
                raise Exception(
                    f"Failed to get person assignments: pagination exceeded "
                    f"{self.MAX_PAGES} pages for endpoint {endpoint}")
            page_params = dict(params or {}, page=page) if page > 1 else params
            response = self.get(endpoint, params=page_params)
            if response.status_code != 200:
                raise Exception(f"Failed to get person assignments: {response.status_code} - {response.text}")

            data = response.json() or {}
            if result is None:
                result = data
            else:
                result.setdefault('todos', []).extend(data.get('todos') or [])

            link_header = response.headers.get("Link", "")
            if not data.get('todos') or 'rel="next"' not in link_header:
                break

            page += 1

        return result

    def get_overdue_todos(self):
        """Get all overdue to-dos across all projects, grouped by lateness.

        Wraps `GET /reports/todos/overdue.json`.

        Returns:
            dict: Groups `under_a_week_late`, `over_a_week_late`,
                `over_a_month_late`, `over_three_months_late`
        """
        response = self.get('reports/todos/overdue.json')
        if response.status_code != 200:
            raise Exception(f"Failed to get overdue todos: {response.status_code} - {response.text}")
        return response.json()

    # Campfire (chat) methods
    def get_campfires(self, project_id):
        """Get the campfires for a project, handling pagination."""
        return self.get_all_pages(f'buckets/{project_id}/chats.json',
                                  error_label="campfires")

    def get_campfire_lines(self, project_id, campfire_id):
        """Get chat lines from a campfire, handling pagination."""
        return self.get_all_pages(
            f'buckets/{project_id}/chats/{campfire_id}/lines.json',
            error_label="campfire lines")

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
        dock_item = self._find_dock_item(project, "message_board")
        if dock_item is None:
            raise Exception(f"No message board found for project: {project_id}")

        board_id = dock_item['id']
        response = self.get(f'buckets/{project_id}/message_boards/{board_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get message board: {response.status_code} - {response.text}")

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

        return self.get_all_pages(
            f'buckets/{project_id}/message_boards/{message_board_id}/messages.json',
            error_label="messages")

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
        return self.get_all_pages(f'buckets/{project_id}/categories.json',
                                  error_label="message categories")

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
        dock_item = self._find_dock_item(project, "inbox")
        if dock_item is None:
            raise Exception(f"No inbox found for project: {project_id}")

        inbox_id = dock_item['id']
        response = self.get(f'buckets/{project_id}/inboxes/{inbox_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get inbox: {response.status_code} - {response.text}")

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

        return self.get_all_pages(
            f'buckets/{project_id}/inboxes/{inbox_id}/forwards.json',
            error_label="forwards")

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
        return self.get_all_pages(
            f'buckets/{project_id}/inbox_forwards/{forward_id}/replies.json',
            error_label="inbox replies")

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
        """Get the schedule for a project."""
        response = self.get(f'projects/{project_id}/schedule.json')
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
        # The schedule ID is discovered from the project's dock array,
        # following the same pattern as get_todoset().
        project = self.get_project(project_id)
        dock_item = self._find_dock_item(project, "schedule")
        if dock_item is None:
            return []

        return self.get_all_pages(
            f"buckets/{project_id}/schedules/{dock_item['id']}/entries.json",
            error_label="schedule entries")

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

    def get_daily_check_ins(self, project_id, page=1):
        project = self.get_project(project_id)
        questionnaire = next(_ for _ in project["dock"] if _["name"] == "questionnaire")
        endpoint = f"buckets/{project_id}/questionnaires/{questionnaire['id']}/questions.json"
        response = self.get(endpoint, params={"page": page})
        if response.status_code != 200:
            raise Exception("Failed to read questions")
        return response.json()

    def get_question_answers(self, project_id, question_id, page=1):
        endpoint = f"buckets/{project_id}/questions/{question_id}/answers.json"
        response = self.get(endpoint, params={"page": page})
        if response.status_code != 200:
            raise Exception("Failed to read question answers")
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
        """Get all cards in a column, handling pagination."""
        return self.get_all_pages(
            f'buckets/{project_id}/card_tables/lists/{column_id}/cards.json',
            error_label="cards")

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

    def move_card(self, project_id, card_id, column_id):
        """Move a card to a new column."""
        data = {"column_id": column_id}
        response = self.post(f'buckets/{project_id}/card_tables/cards/{card_id}/moves.json', data)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to move card: {response.status_code} - {response.text}")

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

        endpoint = f"attachments.json?name={name}"
        response = requests.post(f"{self.base_url}/{endpoint}", auth=self.auth, headers=headers, data=data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create attachment: {response.status_code} - {response.text}")

    def get_events(self, project_id, recording_id):
        """Get events for a recording, handling pagination."""
        return self.get_all_pages(
            f"buckets/{project_id}/recordings/{recording_id}/events.json",
            error_label="events")

    def get_webhooks(self, project_id):
        """List webhooks for a project, handling pagination."""
        return self.get_all_pages(f"buckets/{project_id}/webhooks.json",
                                  error_label="webhooks")

    def create_webhook(self, project_id, payload_url, types=None):
        """Create a webhook for a project."""
        data = {"payload_url": payload_url}
        if types:
            data["types"] = types
        endpoint = f"buckets/{project_id}/webhooks.json"
        response = self.post(endpoint, data)
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to create webhook: {response.status_code} - {response.text}")

    def delete_webhook(self, project_id, webhook_id):
        """Delete a webhook."""
        endpoint = f"buckets/{project_id}/webhooks/{webhook_id}.json"
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to delete webhook: {response.status_code} - {response.text}")

    def get_documents(self, project_id, vault_id):
        """List documents in a vault, handling pagination."""
        return self.get_all_pages(
            f"buckets/{project_id}/vaults/{vault_id}/documents.json",
            error_label="documents")

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
        """List uploads in a project or vault, handling pagination."""
        if vault_id:
            endpoint = f"buckets/{project_id}/vaults/{vault_id}/uploads.json"
        else:
            endpoint = f"buckets/{project_id}/uploads.json"
        return self.get_all_pages(endpoint, error_label="uploads")

    def get_upload(self, project_id, upload_id):
        """Get a single upload."""
        endpoint = f"buckets/{project_id}/uploads/{upload_id}.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get upload: {response.status_code} - {response.text}")

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
            timeout=(10, 300),
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
                timeout=(10, 300),
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
