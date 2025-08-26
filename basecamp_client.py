import os

import requests
from dotenv import load_dotenv


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
        return requests.get(url, auth=self.auth, headers=self.headers, params=params)

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
        """Get all projects."""
        response = self.get('projects.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get projects: {response.status_code} - {response.text}")

    def get_project(self, project_id):
        """Get a specific project by ID."""
        response = self.get(f'projects/{project_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get project: {response.status_code} - {response.text}")

    # To-do list methods
    def get_todoset(self, project_id):
        """Get the todoset for a project (Basecamp 3 has one todoset per project)."""
        project = self.get_project(project_id)
        try:
            return next(_ for _ in project["dock"] if _["name"] == "todoset")
        except (IndexError, TypeError, StopIteration):
            raise Exception(f"Failed to get todoset for project: {project.id}. Project response: {project}")
    
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

    def get_todolist(self, todolist_id):
        """Get a specific todolist."""
        response = self.get(f'todolists/{todolist_id}.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get todolist: {response.status_code} - {response.text}")

    # To-do methods
    def get_todos(self, project_id, todolist_id):
        """Get all todos in a todolist."""
        response = self.get(f'buckets/{project_id}/todolists/{todolist_id}/todos.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get todos: {response.status_code} - {response.text}")

    def get_todo(self, todo_id):
        """Get a specific todo."""
        response = self.get(f'todos/{todo_id}.json')
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
        
        if description:
            data['description'] = description
        if assignee_ids:
            data['assignee_ids'] = assignee_ids
        if completion_subscriber_ids:
            data['completion_subscriber_ids'] = completion_subscriber_ids
        if notify:
            data['notify'] = notify
        if due_on:
            data['due_on'] = due_on
        if starts_on:
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
        Delete a todo item.
        
        Args:
            project_id (str): Project ID
            todo_id (str): Todo ID
            
        Returns:
            bool: True if successful
        """
        endpoint = f'buckets/{project_id}/todos/{todo_id}.json'
        response = self.delete(endpoint)
        if response.status_code == 204:
            return True
        else:
            raise Exception(f"Failed to delete todo: {response.status_code} - {response.text}")

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
        if response.status_code == 201:
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

    # People methods
    def get_people(self):
        """Get all people in the account."""
        response = self.get('people.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get people: {response.status_code} - {response.text}")

    # Campfire (chat) methods
    def get_campfires(self, project_id):
        """Get the campfire for a project."""
        response = self.get(f'buckets/{project_id}/chats.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get campfire: {response.status_code} - {response.text}")

    def get_campfire_lines(self, project_id, campfire_id):
        """Get chat lines from a campfire."""
        response = self.get(f'buckets/{project_id}/chats/{campfire_id}/lines.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get campfire lines: {response.status_code} - {response.text}")

    # Message board methods
    def get_message_board(self, project_id):
        """Get the message board for a project."""
        response = self.get(f'projects/{project_id}/message_board.json')
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get message board: {response.status_code} - {response.text}")

    def get_messages(self, project_id):
        """Get all messages for a project."""
        # First get the message board ID
        message_board = self.get_message_board(project_id)
        message_board_id = message_board['id']

        # Then get all messages
        response = self.get('messages.json', {'message_board_id': message_board_id})
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get messages: {response.status_code} - {response.text}")

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
        try:
            endpoint = f"buckets/{project_id}/schedules.json"
            schedule = self.get(endpoint)

            if isinstance(schedule, list) and len(schedule) > 0:
                schedule_id = schedule[0]['id']
                entries_endpoint = f"buckets/{project_id}/schedules/{schedule_id}/entries.json"
                return self.get(entries_endpoint)
            else:
                return []
        except Exception as e:
            raise Exception(f"Failed to get schedule: {str(e)}")

    # Comments methods
    def get_comments(self, project_id, recording_id):
        """
        Get all comments for a recording (todos, message, etc.).
        
        Args:
            recording_id (int): ID of the recording (todos, message, etc.)
            project_id (int): Project/bucket ID. If not provided, it will be extracted from the recording ID.
            
        Returns:
            list: Comments for the recording
        """
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/comments.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
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
        if response.status_code == 201:
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
        response = self.post(f'buckets/{project_id}/todos/{step_id}/completion.json')
        if response.status_code == 201:
            return response.json()
        else:
            raise Exception(f"Failed to complete card step: {response.status_code} - {response.text}")

    def uncomplete_card_step(self, project_id, step_id):
        """Mark a card step as incomplete."""
        response = self.delete(f'buckets/{project_id}/todos/{step_id}/completion.json')
        if response.status_code == 204:
            return True
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
        """Get events for a recording."""
        endpoint = f"buckets/{project_id}/recordings/{recording_id}/events.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get events: {response.status_code} - {response.text}")

    def get_webhooks(self, project_id):
        """List webhooks for a project."""
        endpoint = f"buckets/{project_id}/webhooks.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get webhooks: {response.status_code} - {response.text}")

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
        """List documents in a vault."""
        endpoint = f"buckets/{project_id}/vaults/{vault_id}/documents.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get documents: {response.status_code} - {response.text}")

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
        data = {"title": title, "content": content, "status": status}
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
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get uploads: {response.status_code} - {response.text}")

    def get_upload(self, project_id, upload_id):
        """Get a single upload."""
        endpoint = f"buckets/{project_id}/uploads/{upload_id}.json"
        response = self.get(endpoint)
        if response.status_code == 200:
            return response.json()
        else:
            raise Exception(f"Failed to get upload: {response.status_code} - {response.text}")
