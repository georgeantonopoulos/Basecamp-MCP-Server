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
