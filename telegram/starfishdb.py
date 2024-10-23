import mysql.connector
from functools import wraps
from config import DB_CONFIG, BOT_TOKEN
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def with_db_connection(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        try:
            result = func(self, *args, **kwargs)
            return result
        except Exception as e:
            logger.error(f"Database error in {func.__name__}: {str(e)}")
            raise
        finally:
            self.cursor.close()
            self.conn.close()
    return wrapper

class StarfishDB:
    def __init__(self):
        """Initializes the StarfishDB class."""
        self.token = BOT_TOKEN
        self.conn = None
        self.cursor = None

    @with_db_connection
    def user_exists(self, username):
        """Check if a user exists in Student table."""
        query = "SELECT EXISTS(SELECT 1 FROM Student WHERE TelegramUsername = %s)"
        self.cursor.execute(query, (username,))
        return self.cursor.fetchone()[0]

    @with_db_connection
    def update_channel_id(self, username, chat_id):
        """Updates the chat_id for a user in the user_channels table."""
        # First, get the ChannelID from Student table
        query = "SELECT ChannelID FROM Student WHERE TelegramUsername = %s"
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()
        
        if not result:
            raise Exception("Student not found")
            
        channel_id = result[0]
        
        # Check if entry exists in user_channels
        query = "SELECT 1 FROM user_channels WHERE username = %s"
        self.cursor.execute(query, (username,))
        exists = self.cursor.fetchone()
        
        if exists:
            # Update existing record
            query = """
            UPDATE user_channels 
            SET chat_id = %s,
                last_updated = CURRENT_TIMESTAMP
            WHERE username = %s AND channel_id = %s
            """
            self.cursor.execute(query, (chat_id, username, channel_id))
        else:
            # Insert new record
            query = """
            INSERT INTO user_channels (username, channel_id, chat_id, last_updated) 
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            """
            self.cursor.execute(query, (username, channel_id, chat_id))
        
        self.conn.commit()

    @with_db_connection
    def get_channel_id(self, username):
        """Gets the chat_id for a user."""
        query = "SELECT chat_id FROM user_channels WHERE username = %s"
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()
        return result[0] if result else None

    @with_db_connection
    def get_student_details(self, username):
        """Get student details including attendance status."""
        query = """
        SELECT s.StudentName, s.StudentID, s.ChannelID,
               a.AttendanceStatus, a.TimeAttended, a.Reason,
               c.ClassDate
        FROM Student s
        JOIN user_channels uc ON s.ChannelID = uc.channel_id
        LEFT JOIN Attendance a ON s.StudentID = a.StudentID
        LEFT JOIN Classes c ON a.ClassID = c.ClassID
        WHERE uc.username = %s
        ORDER BY c.ClassDate DESC
        LIMIT 1
        """
        self.cursor.execute(query, (username,))
        return self.cursor.fetchone()

    @with_db_connection
    def get_absent_students(self, check_date):
        """Get all students who are absent/not marked present for today"""
        query = """
        SELECT s.StudentID, s.StudentName, s.TelegramUsername as username
        FROM Student s
        LEFT JOIN Attendance a ON s.StudentID = a.StudentID
        LEFT JOIN Classes c ON a.ClassID = c.ClassID
        WHERE DATE(c.ClassDate) = %s 
        AND (a.AttendanceStatus IS NULL 
             OR a.AttendanceStatus IN ('Absent', 'Late'))
        """
        self.cursor.execute(query, (check_date,))
        return self.cursor.fetchall()

    @with_db_connection
    def set_awaiting_late_reason(self, username):
        """Mark a student as awaiting a late reason"""
        query = """
        UPDATE user_channels 
        SET awaiting_reason = 1,
            last_updated = CURRENT_TIMESTAMP
        WHERE username = %s
        """
        self.cursor.execute(query, (username,))
        self.conn.commit()

    @with_db_connection
    def clear_awaiting_late_reason(self, username):
        """Clear the awaiting reason flag for a student"""
        query = """
        UPDATE user_channels 
        SET awaiting_reason = 0,
            last_updated = CURRENT_TIMESTAMP
        WHERE username = %s
        """
        self.cursor.execute(query, (username,))
        self.conn.commit()

    @with_db_connection
    def is_awaiting_late_reason(self, username):
        """Check if a student is awaiting a late reason"""
        query = """
        SELECT awaiting_reason 
        FROM user_channels 
        WHERE username = %s
        """
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()
        return result[0] if result else False

    @with_db_connection
    def update_reason(self, username, reason):
        """Update the late reason and clear the awaiting flag"""
        query = """
        UPDATE user_channels 
        SET reason_for_late = %s,
            awaiting_reason = 0,
            last_updated = CURRENT_TIMESTAMP
        WHERE username = %s
        """
        self.cursor.execute(query, (reason, username))
        self.conn.commit()

        # Also update the Attendance table
        query = """
        UPDATE Attendance a
        JOIN Student s ON a.StudentID = s.StudentID
        JOIN Classes c ON a.ClassID = c.ClassID
        SET a.Reason = %s
        WHERE s.TelegramUsername = %s
        AND DATE(c.ClassDate) = CURDATE()
        """
        self.cursor.execute(query, (reason, username))
        self.conn.commit()

    @with_db_connection
    def get_today_class_id(self):
        """Get the class ID for today's class"""
        query = """
        SELECT ClassID 
        FROM Classes 
        WHERE DATE(ClassDate) = CURDATE()
        """
        self.cursor.execute(query)
        result = self.cursor.fetchone()
        return result[0] if result else None