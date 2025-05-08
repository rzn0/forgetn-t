# database.py
import sqlite3
import logging
from typing import Optional, List, Dict

DATABASE_NAME = 'tasks.db'
logger = logging.getLogger('discord')

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row # Return rows as dictionary-like objects
    return conn

def _column_exists(cursor, table_name, column_name):
    """Checks if a column exists in a table."""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row['name'] for row in cursor.fetchall()]
    return column_name in columns

def initialize_database():
    """Creates the necessary tables and columns if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Guild configuration table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS guilds (
                guild_id INTEGER PRIMARY KEY,
                open_channel_id INTEGER,
                inprogress_channel_id INTEGER
            )
        ''')

        # Add completed_channel_id if it doesn't exist (for backward compatibility)
        if not _column_exists(cursor, 'guilds', 'completed_channel_id'):
            cursor.execute('ALTER TABLE guilds ADD COLUMN completed_channel_id INTEGER')
            logger.info("Added 'completed_channel_id' column to 'guilds' table.")

        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('open', 'in_progress')),
                creator_id INTEGER NOT NULL,
                assignee_id INTEGER,
                open_message_id INTEGER UNIQUE,
                inprogress_message_id INTEGER UNIQUE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (guild_id) REFERENCES guilds (guild_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_guild_status ON tasks (guild_id, status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_open_message ON tasks (open_message_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_task_inprogress_message ON tasks (inprogress_message_id)')

        conn.commit()
        logger.info("Database initialized successfully.")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        conn.rollback()
    finally:
        conn.close()

# --- Guild Configuration Functions ---

def set_channel(guild_id: int, channel_type: str, channel_id: int) -> bool:
    """Sets the open, in-progress, or completed channel ID for a guild."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if channel_type not in ['open', 'inprogress', 'completed']:
            logger.error(f"Invalid channel type: {channel_type}")
            return False
        column_name = f"{channel_type}_channel_id"
        # Create guild row if it doesn't exist, then update channel ID.
        cursor.execute("INSERT OR IGNORE INTO guilds (guild_id) VALUES (?)", (guild_id,))
        cursor.execute(f"UPDATE guilds SET {column_name} = ? WHERE guild_id = ?", (channel_id, guild_id))
        conn.commit()
        logger.info(f"Set {channel_type} channel for guild {guild_id} to {channel_id}")
        return True
    except sqlite3.Error as e:
        logger.error(f"Error setting {channel_type} channel for guild {guild_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_channel_ids(guild_id: int) -> Optional[Dict[str, Optional[int]]]:
    """Gets the configured channel IDs for a guild."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT open_channel_id, inprogress_channel_id, completed_channel_id FROM guilds WHERE guild_id = ?", (guild_id,))
        row = cursor.fetchone()
        if row:
            return {
                'open': row['open_channel_id'],
                'inprogress': row['inprogress_channel_id'],
                'completed': row['completed_channel_id']
            }
        return None # Guild not found in DB
    except sqlite3.Error as e:
        logger.error(f"Error getting channel IDs for guild {guild_id}: {e}")
        return None
    finally:
        conn.close()

# --- Task Management Functions ---

def add_task(guild_id: int, description: str, creator_id: int) -> Optional[int]:
    """Adds a new task to the database with 'open' status. Returns the new task ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO tasks (guild_id, description, status, creator_id) VALUES (?, ?, 'open', ?)",
            (guild_id, description, creator_id)
        )
        conn.commit()
        task_id = cursor.lastrowid
        logger.info(f"Added task {task_id} for guild {guild_id} by user {creator_id}")
        return task_id
    except sqlite3.Error as e:
        logger.error(f"Error adding task for guild {guild_id}: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()

def get_task_by_id(task_id: int) -> Optional[sqlite3.Row]:
    """Retrieves a specific task by its ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
        return cursor.fetchone()
    except sqlite3.Error as e:
        logger.error(f"Error getting task {task_id}: {e}")
        return None
    finally:
        conn.close()

def get_task_by_message_id(message_id: int) -> Optional[sqlite3.Row]:
    """Retrieves a specific task by its message ID (open or in-progress)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM tasks WHERE open_message_id = ? OR inprogress_message_id = ?", (message_id, message_id))
        return cursor.fetchone()
    except sqlite3.Error as e:
        logger.error(f"Error getting task by message ID {message_id}: {e}")
        return None
    finally:
        conn.close()

def get_tasks_by_status(guild_id: int, status: str) -> List[sqlite3.Row]:
    """Retrieves all tasks for a guild with a specific status."""
    conn = get_db_connection()
    cursor = conn.cursor()
    tasks_list = []
    try:
        cursor.execute("SELECT * FROM tasks WHERE guild_id = ? AND status = ?", (guild_id, status))
        tasks_list = cursor.fetchall()
    except sqlite3.Error as e:
        logger.error(f"Error getting tasks by status ({status}) for guild {guild_id}: {e}")
    finally:
        conn.close()
    return tasks_list

def update_task_message_id(task_id: int, message_type: str, message_id: Optional[int]) -> bool:
    """Updates the message ID for a task (open or inprogress)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if message_type not in ['open', 'inprogress']:
            logger.error(f"Invalid message type for updating message ID: {message_type}")
            return False
        column_name = f"{message_type}_message_id"
        cursor.execute(f"UPDATE tasks SET {column_name} = ? WHERE task_id = ?", (message_id, task_id))
        conn.commit()
        return True
    except sqlite3.IntegrityError: # Catch if trying to set a duplicate message_id
         logger.warning(f"Attempted to set duplicate {message_type}_message_id {message_id} for task {task_id}.")
         conn.rollback()
         return False
    except sqlite3.Error as e:
        logger.error(f"Error updating {column_name} for task {task_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def claim_task(task_id: int, assignee_id: int) -> bool:
    """Updates task status to 'in_progress' and sets the assignee."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE tasks SET status = 'in_progress', assignee_id = ? WHERE task_id = ? AND status = 'open'",
            (assignee_id, task_id)
        )
        updated_rows = cursor.rowcount
        conn.commit()
        if updated_rows > 0:
            logger.info(f"Task {task_id} claimed by user {assignee_id}")
            return True
        else:
            logger.warning(f"Task {task_id} could not be claimed (already claimed, completed, or doesn't exist).")
            return False
    except sqlite3.Error as e:
        logger.error(f"Error claiming task {task_id} for user {assignee_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def complete_task_in_db(task_id: int) -> bool:
    """Deletes a task from the database. This is called *after* logging to completed channel."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM tasks WHERE task_id = ? AND status = 'in_progress'", (task_id,))
        deleted_rows = cursor.rowcount
        conn.commit()
        if deleted_rows > 0:
            logger.info(f"Task {task_id} permanently deleted from database.")
            return True
        else:
            logger.warning(f"Task {task_id} could not be deleted from database (not found or not in 'in_progress' status).")
            return False
    except sqlite3.Error as e:
        logger.error(f"Error deleting task {task_id} from database: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# --- Utility Functions ---

def remove_task_by_message_id(message_id: int) -> bool:
    """Deletes a task from the database based on one of its message IDs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM tasks WHERE open_message_id = ? OR inprogress_message_id = ?", (message_id, message_id))
        deleted_rows = cursor.rowcount
        conn.commit()
        if deleted_rows > 0:
            logger.info(f"Task associated with message {message_id} removed from DB.")
            return True
        return False
    except sqlite3.Error as e:
        logger.error(f"Error removing task by message ID {message_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def cleanup_guild_data(guild_id: int):
    """Removes all tasks and guild configuration for a specific guild."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM tasks WHERE guild_id = ?", (guild_id,))
        cursor.execute("DELETE FROM guilds WHERE guild_id = ?", (guild_id,))
        conn.commit()
        logger.info(f"Cleaned up all data for guild {guild_id}")
    except sqlite3.Error as e:
        logger.error(f"Error cleaning up data for guild {guild_id}: {e}")
        conn.rollback()
    finally:
        conn.close()