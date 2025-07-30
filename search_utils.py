from basecamp_client import BasecampClient
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('basecamp_search')

class BasecampSearch:
    """
    Utility for searching across Basecamp 3 projects and to-dos.
    """

    def __init__(self, client=None, **kwargs):
        """Initialize with either an existing client or credentials."""
        if client:
            self.client = client
        else:
            self.client = BasecampClient(**kwargs)

    def search_projects(self, query=None):
        """
        Search all projects, optionally filtering by name.

        Args:
            query (str, optional): Text to search for in project names

        Returns:
            list: Filtered list of projects
        """
        try:
            projects = self.client.get_projects()

            if query and projects:
                query = query.lower()
                projects = [
                    project for project in projects
                    if query in project.get('name', '').lower() or
                    query in (project.get('description') or '').lower()
                ]

            return projects
        except Exception as e:
            logger.error(f"Error searching projects: {str(e)}")
            return []

    def get_all_todolists(self, project_id=None):
        """
        Get all todolists, either for a specific project or across all projects.

        Args:
            project_id (int, optional): Specific project ID or None for all projects

        Returns:
            list: List of todolists with project info
        """
        all_todolists = []

        try:
            if project_id:
                # Get todolists for a specific project
                project = self.client.get_project(project_id)
                todolists = self.client.get_todolists(project_id)

                for todolist in todolists:
                    todolist['project'] = {'id': project['id'], 'name': project['name']}
                    all_todolists.append(todolist)
            else:
                # Get todolists across all projects
                projects = self.client.get_projects()

                for project in projects:
                    project_id = project['id']
                    try:
                        todolists = self.client.get_todolists(project_id)
                        for todolist in todolists:
                            todolist['project'] = {'id': project['id'], 'name': project['name']}
                            all_todolists.append(todolist)
                    except Exception as e:
                        logger.error(f"Error getting todolists for project {project_id}: {str(e)}")
        except Exception as e:
            logger.error(f"Error getting all todolists: {str(e)}")

        return all_todolists

    def search_todolists(self, query=None, project_id=None):
        """
        Search all todolists, optionally filtering by name and project.

        Args:
            query (str, optional): Text to search for in todolist names
            project_id (int, optional): Specific project ID or None for all projects

        Returns:
            list: Filtered list of todolists
        """
        todolists = self.get_all_todolists(project_id)

        if query and todolists:
            query = query.lower()
            todolists = [
                todolist for todolist in todolists
                if query in todolist.get('name', '').lower() or
                query in (todolist.get('description') or '').lower()
            ]

        return todolists

    def get_all_todos(self, project_id=None, todolist_id=None, include_completed=False):
        """
        Get all todos, with various filtering options.

        Args:
            project_id (int, optional): Specific project ID or None for all projects
            todolist_id (int, optional): Specific todolist ID or None for all todolists
            include_completed (bool): Whether to include completed todos

        Returns:
            list: List of todos with project and todolist info
        """
        all_todos = []

        try:
            # Case 1: Specific todolist (regardless of project)
            if todolist_id:
                try:
                    todolist = self.client.get_todolist(todolist_id)
                    todos = self.client.get_todos(todolist_id)

                    # In Basecamp 3, we need to add project info to the todolist
                    # Get project ID from the URL
                    project_links = [link for link in todolist.get('bucket', {}).get('links', [])
                                   if link.get('type') == 'project']
                    if project_links:
                        project_url = project_links[0].get('href', '')
                        # Extract project ID from URL
                        parts = project_url.split('/')
                        if len(parts) > 0:
                            project_id = parts[-1]
                            try:
                                project = self.client.get_project(project_id)
                                project_name = project.get('name', 'Unknown Project')
                            except:
                                project_name = 'Unknown Project'
                        else:
                            project_name = 'Unknown Project'
                    else:
                        project_name = 'Unknown Project'

                    for todo in todos:
                        if not include_completed and todo.get('completed'):
                            continue

                        todo['project'] = {'id': project_id, 'name': project_name}
                        todo['todolist'] = {'id': todolist['id'], 'name': todolist['name']}
                        all_todos.append(todo)
                except Exception as e:
                    logger.error(f"Error getting todos for todolist {todolist_id}: {str(e)}")

            # Case 2: Specific project, all todolists
            elif project_id:
                project = self.client.get_project(project_id)
                todolists = self.client.get_todolists(project_id)

                for todolist in todolists:
                    try:
                        todos = self.client.get_todos(todolist['id'])
                        for todo in todos:
                            if not include_completed and todo.get('completed'):
                                continue

                            todo['project'] = {'id': project['id'], 'name': project['name']}
                            todo['todolist'] = {'id': todolist['id'], 'name': todolist['name']}
                            all_todos.append(todo)
                    except Exception as e:
                        logger.error(f"Error getting todos for todolist {todolist['id']}: {str(e)}")

            # Case 3: All projects
            else:
                todolists = self.get_all_todolists()

                for todolist in todolists:
                    try:
                        todos = self.client.get_todos(todolist['id'])
                        for todo in todos:
                            if not include_completed and todo.get('completed'):
                                continue

                            todo['project'] = todolist['project']
                            todo['todolist'] = {'id': todolist['id'], 'name': todolist['name']}
                            all_todos.append(todo)
                    except Exception as e:
                        logger.error(f"Error getting todos for todolist {todolist['id']}: {str(e)}")
        except Exception as e:
            logger.error(f"Error getting all todos: {str(e)}")

        return all_todos

    def search_todos(self, query=None, project_id=None, todolist_id=None, include_completed=False):
        """
        Search all todos, with various filtering options.

        Args:
            query (str, optional): Text to search for in todo content
            project_id (int, optional): Specific project ID or None for all projects
            todolist_id (int, optional): Specific todolist ID or None for all todolists
            include_completed (bool): Whether to include completed todos

        Returns:
            list: Filtered list of todos
        """
        todos = self.get_all_todos(project_id, todolist_id, include_completed)

        if query and todos:
            query = query.lower()
            # In Basecamp 3, the todo content is in the 'content' field
            todos = [
                t for t in todos
                if query in t.get('content', '').lower() or
                query in (t.get('description') or '').lower()
            ]

        return todos

    def search_messages(self, query=None, project_id=None):
        """
        Search for messages across all projects or within a specific project.

        Args:
            query (str, optional): Search term to filter messages
            project_id (int, optional): If provided, only search within this project

        Returns:
            list: Matching messages
        """
        all_messages = []

        try:
            # Get projects to search in
            if project_id:
                projects = [self.client.get_project(project_id)]
            else:
                projects = self.client.get_projects()

            for project in projects:
                project_id = project['id']
                logger.info(f"Searching messages in project {project_id} ({project.get('name', 'Unknown')})")

                # Check for message boards in the dock
                has_message_board = False
                message_boards = []

                for dock_item in project.get('dock', []):
                    if dock_item.get('name') == 'message_board' and dock_item.get('enabled', False):
                        has_message_board = True
                        message_boards.append(dock_item)

                if not has_message_board:
                    logger.info(f"Project {project_id} ({project.get('name', 'Unknown')}) has no enabled message boards")
                    continue

                # Get messages from each message board
                for board in message_boards:
                    board_id = board.get('id')
                    try:
                        # First try getting the message board details
                        logger.info(f"Fetching message board {board_id} for project {project_id}")
                        board_endpoint = f"buckets/{project_id}/message_boards/{board_id}.json"
                        board_details = self.client.get(board_endpoint)

                        # Then get all messages in the board
                        logger.info(f"Fetching messages for board {board_id} in project {project_id}")
                        messages_endpoint = f"buckets/{project_id}/message_boards/{board_id}/messages.json"
                        messages = self.client.get(messages_endpoint)

                        logger.info(f"Found {len(messages)} messages in board {board_id}")

                        # Now get detailed content for each message
                        for message in messages:
                            try:
                                message_id = message.get('id')
                                # Get detailed message content
                                message_endpoint = f"buckets/{project_id}/messages/{message_id}.json"
                                detailed_message = self.client.get(message_endpoint)

                                # Add project info
                                detailed_message['project'] = {
                                    'id': project_id,
                                    'name': project.get('name', 'Unknown Project')
                                }

                                # Add to results
                                all_messages.append(detailed_message)
                            except Exception as e:
                                logger.error(f"Error getting detailed message {message.get('id', 'unknown')} in project {project_id}: {str(e)}")
                                # Still include basic message info
                                message['project'] = {
                                    'id': project_id,
                                    'name': project.get('name', 'Unknown Project')
                                }
                                all_messages.append(message)
                    except Exception as e:
                        logger.error(f"Error getting messages for board {board_id} in project {project_id}: {str(e)}")

                        # Try alternate approach: get messages directly for the project
                        try:
                            logger.info(f"Trying alternate approach for project {project_id}")
                            messages = self.client.get_messages(project_id)

                            logger.info(f"Found {len(messages)} messages in project {project_id} using direct method")

                            # Add project info to each message
                            for message in messages:
                                message['project'] = {
                                    'id': project_id,
                                    'name': project.get('name', 'Unknown Project')
                                }
                                all_messages.append(message)
                        except Exception as e2:
                            logger.error(f"Error getting messages directly for project {project_id}: {str(e2)}")

                # Also check for message categories/topics
                try:
                    # Try to get message categories
                    categories_endpoint = f"buckets/{project_id}/categories.json"
                    categories = self.client.get(categories_endpoint)

                    for category in categories:
                        category_id = category.get('id')
                        try:
                            # Get messages in this category
                            category_messages_endpoint = f"buckets/{project_id}/categories/{category_id}/messages.json"
                            category_messages = self.client.get(category_messages_endpoint)

                            # Add project and category info
                            for message in category_messages:
                                message['project'] = {
                                    'id': project_id,
                                    'name': project.get('name', 'Unknown Project')
                                }
                                message['category'] = {
                                    'id': category_id,
                                    'name': category.get('name', 'Unknown Category')
                                }
                                all_messages.append(message)
                        except Exception as e:
                            logger.error(f"Error getting messages for category {category_id} in project {project_id}: {str(e)}")
                except Exception as e:
                    logger.info(f"No message categories found for project {project_id}: {str(e)}")

        except Exception as e:
            logger.error(f"Error searching messages: {str(e)}")

        # Filter by query if provided
        if query and all_messages:
            query = query.lower()
            filtered_messages = []

            for message in all_messages:
                # Search in multiple fields
                content_matched = False

                # Check title/subject
                if query in (message.get('subject', '') or '').lower():
                    content_matched = True

                # Check content field
                if not content_matched and query in (message.get('content', '') or '').lower():
                    content_matched = True

                # Check content field with HTML
                if not content_matched and 'content' in message:
                    content_html = message.get('content')
                    if content_html and query in content_html.lower():
                        content_matched = True

                # Check raw content in various formats
                if not content_matched:
                    # Try different content field formats
                    for field in ['raw_content', 'content_html', 'body', 'description', 'text']:
                        if field in message and message[field]:
                            if query in str(message[field]).lower():
                                content_matched = True
                                break

                # Check title field
                if not content_matched and 'title' in message and message['title']:
                    if query in message['title'].lower():
                        content_matched = True

                # Check creator's name
                if not content_matched and 'creator' in message and message['creator']:
                    creator = message['creator']
                    creator_name = f"{creator.get('name', '')} {creator.get('first_name', '')} {creator.get('last_name', '')}"
                    if query in creator_name.lower():
                        content_matched = True

                # Include if content matched
                if content_matched:
                    filtered_messages.append(message)

            logger.info(f"Found {len(filtered_messages)} messages matching query '{query}' out of {len(all_messages)} total messages")
            return filtered_messages

        return all_messages

    def search_schedule_entries(self, query=None, project_id=None):
        """
        Search schedule entries across projects or in a specific project.

        Args:
            query (str, optional): Search term to filter schedule entries
            project_id (int, optional): Specific project ID to search in

        Returns:
            list: Matching schedule entries
        """
        try:
            # Get the schedule entries (from all projects or a specific one)
            if project_id:
                entries = self.client.get_schedule_entries(project_id)
                entries = entries.json() if hasattr(entries, 'json') else entries
            else:
                # Get all projects first
                projects = self.client.get_projects()

                # Then get schedule entries from each
                entries = []
                for project in projects:
                    project_entries = self.client.get_schedule_entries(project['id'])
                    project_entries = project_entries.json() if hasattr(project_entries, 'json') else project_entries
                    if project_entries:
                        for entry in project_entries:
                            entry['project'] = {
                                'id': project['id'],
                                'name': project['name']
                            }
                        entries.extend(project_entries)

            # Filter by query if provided
            if query and entries:
                query = query.lower()
                entries = [
                    entry for entry in entries
                    if query in entry.get('title', '').lower() or
                    query in (entry.get('description') or '').lower() or
                    (entry.get('creator') and query in entry['creator'].get('name', '').lower())
                ]

            return entries
        except Exception as e:
            logger.error(f"Error searching schedule entries: {str(e)}")
            return []

    def search_comments(self, query=None, recording_id=None, bucket_id=None):
        """
        Search for comments across resources or for a specific resource.

        Args:
            query (str, optional): Search term to filter comments
            recording_id (int, optional): ID of the recording (todo, message, etc.) to search in
            bucket_id (int, optional): Project/bucket ID

        Returns:
            list: Matching comments
        """
        try:
            # If both recording_id and bucket_id are provided, get comments for that specific recording
            if recording_id and bucket_id:
                comments = self.client.get_comments(recording_id, bucket_id)
            # Otherwise we can't search across all comments as there's no endpoint for that
            else:
                logger.warning("Cannot search all comments across Basecamp - both recording_id and bucket_id are required")
                return [{
                    "content": "To search comments, you need to specify both a recording ID (todo, message, etc.) and a bucket ID. Comments cannot be searched globally in Basecamp.",
                    "api_limitation": True,
                    "title": "Comment Search Limitation"
                }]

            # Filter by query if provided
            if query and comments:
                query = query.lower()

                filtered_comments = []
                for comment in comments:
                    # Check content
                    content_matched = False
                    content = comment.get('content', '')
                    if content and query in content.lower():
                        content_matched = True

                    # Check creator name
                    if not content_matched and comment.get('creator'):
                        creator_name = comment['creator'].get('name', '')
                        if creator_name and query in creator_name.lower():
                            content_matched = True

                    # If matched, add to results
                    if content_matched:
                        filtered_comments.append(comment)

                return filtered_comments

            return comments
        except Exception as e:
            logger.error(f"Error searching comments: {str(e)}")
            return []

    def search_campfire_lines(self, query=None, project_id=None, campfire_id=None):
        """
        Search for lines in campfire chats.

        Args:
            query (str, optional): Search term to filter lines
            project_id (int, optional): Project ID
            campfire_id (int, optional): Campfire ID

        Returns:
            list: Matching chat lines
        """
        try:
            if not project_id or not campfire_id:
                logger.warning("Cannot search campfire lines without project_id and campfire_id")
                return [{
                    "content": "To search campfire lines, you need to specify both a project ID and a campfire ID.",
                    "api_limitation": True,
                    "title": "Campfire Search Limitation"
                }]

            lines = self.client.get_campfire_lines(project_id, campfire_id)

            if query and lines:
                query = query.lower()

                filtered_lines = []
                for line in lines:
                    # Check content
                    content_matched = False
                    content = line.get('content', '')
                    if content and query in content.lower():
                        content_matched = True

                    # Check creator name
                    if not content_matched and line.get('creator'):
                        creator_name = line['creator'].get('name', '')
                        if creator_name and query in creator_name.lower():
                            content_matched = True

                    # If matched, add to results
                    if content_matched:
                        filtered_lines.append(line)

                return filtered_lines

            return lines
        except Exception as e:
            logger.error(f"Error searching campfire lines: {str(e)}")
            return []

    def search_all_campfire_lines(self, query=None):
        """Search campfire chat lines across all projects."""
        all_lines = []

        try:
            projects = self.client.get_projects()

            for project in projects:
                project_id = project["id"]
                try:
                    campfires = self.client.get_campfires(project_id)
                    for campfire in campfires:
                        campfire_id = campfire["id"]
                        lines = self.client.get_campfire_lines(project_id, campfire_id)

                        for line in lines:
                            line["project"] = {"id": project_id, "name": project.get("name")}
                            line["campfire"] = {"id": campfire_id, "title": campfire.get("title")}
                            all_lines.append(line)
                except Exception as e:
                    logger.error(f"Error getting campfire lines for project {project_id}: {str(e)}")

            if query and all_lines:
                q = query.lower()
                filtered = []
                for line in all_lines:
                    content = line.get("content", "") or ""
                    creator_name = ""
                    if line.get("creator"):
                        creator_name = line["creator"].get("name", "")
                    if q in content.lower() or (creator_name and q in creator_name.lower()):
                        filtered.append(line)
                return filtered

            return all_lines
        except Exception as e:
            logger.error(f"Error searching all campfire lines: {str(e)}")
            return []

    def search_uploads(self, query=None, project_id=None, vault_id=None):
        """Search uploads by filename or content."""
        try:
            all_uploads = []
            
            if project_id:
                # Search within specific project
                projects = [{"id": project_id}]
            else:
                # Search across all projects
                projects = self.client.get_projects()
            
            for project in projects:
                project_id = project["id"]
                try:
                    uploads = self.client.get_uploads(project_id, vault_id)
                    for upload in uploads:
                        upload["project"] = {"id": project_id, "name": project.get("name")}
                        all_uploads.append(upload)
                except Exception as e:
                    logger.error(f"Error getting uploads for project {project_id}: {str(e)}")
            
            if query and all_uploads:
                q = query.lower()
                filtered = []
                for upload in all_uploads:
                    filename = upload.get("filename", "") or ""
                    title = upload.get("title", "") or ""
                    description = upload.get("description", "") or ""
                    creator_name = ""
                    if upload.get("creator"):
                        creator_name = upload["creator"].get("name", "")
                    
                    # Search in filename, title, description, and creator name
                    if (q in filename.lower() or 
                        q in title.lower() or 
                        q in description.lower() or 
                        (creator_name and q in creator_name.lower())):
                        filtered.append(upload)
                return filtered
            
            return all_uploads
        except Exception as e:
            logger.error(f"Error searching uploads: {str(e)}")
            return []

    def global_search(self, query=None):
        """Search projects, todos, campfire lines, and uploads at once."""
        return {
            "projects": self.search_projects(query),
            "todos": self.search_todos(query),
            "campfire_lines": self.search_all_campfire_lines(query),
            "uploads": self.search_uploads(query),
        }
