import mysql.connector
from functools import wraps
from config import DB_CONFIG, BOT_TOKEN
import logging
from datetime import datetime, date

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def with_db_connection(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor(dictionary=True)
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
        self.token = BOT_TOKEN
        self.conn = None
        self.cursor = None

    @with_db_connection
    def get_channel_id(self, username):
        """Get the chat_id for a user."""
        query = "SELECT chat_id FROM user_channels WHERE username = %s"
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()
        print(result)
        return result['chat_id'] if result else None

    @with_db_connection
    def is_awaiting_response(self, username):
        """Check if we're waiting for a response from this student."""
        query = "SELECT awaiting_response FROM user_channels WHERE username = %s"
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()
        return result['awaiting_response'] if result else False

    @with_db_connection
    def set_awaiting_response(self, username):
        """Mark a student as awaiting response."""
        query = """
        UPDATE user_channels 
        SET awaiting_response = 1,
            last_updated = CURRENT_TIMESTAMP
        WHERE username = %s
        """
        self.cursor.execute(query, (username,))
        self.conn.commit()

    @with_db_connection
    def clear_awaiting_response(self, username):
        """Clear the awaiting response flag."""
        query = """
        UPDATE user_channels 
        SET awaiting_response = 0,
            last_updated = CURRENT_TIMESTAMP
        WHERE username = %s
        """
        self.cursor.execute(query, (username,))
        self.conn.commit()

    @with_db_connection
    def update_attendance_with_reason(self, username, reason, status):
        """Update attendance status and reason."""
        today = date.today()
        query = """
        UPDATE Attendance a
        JOIN Student s ON a.StudentID = s.StudentID
        JOIN Classes c ON a.ClassID = c.ClassID
        SET a.AttendanceStatus = %s,
            a.Reason = %s,
            a.TimeAttended = CURRENT_TIME
        WHERE s.TelegramUsername = %s
        AND DATE(c.ClassDate) = %s
        """
        self.cursor.execute(query, (status, reason, username, today))
        self.conn.commit()
        self.clear_awaiting_response(username)

    @with_db_connection
    def get_absent_students(self, check_date):
        """Get all students who haven't been marked present for today."""
        query = """
        SELECT DISTINCT
            s.StudentID,
            s.StudentName,
            s.TelegramUsername as username
        FROM Student s
        LEFT JOIN Attendance a ON s.StudentID = a.StudentID
        LEFT JOIN Classes c ON a.ClassID = c.ClassID
        WHERE DATE(c.ClassDate) = %s
        AND (a.AttendanceStatus IS NULL OR a.AttendanceStatus = 'Absent')
        """
        self.cursor.execute(query, (check_date,))
        return self.cursor.fetchall()

    @with_db_connection
    def get_student_name(self, username):
        """Get student's name from their username."""
        query = "SELECT StudentName FROM Student WHERE TelegramUsername = %s"
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()
        return result['StudentName'] if result else None
    
    @with_db_connection
    def update_channel_id(self, username, channel_id):
        """Sets the channel ID for a user."""
        username = '@'+username
        print(username,channel_id)
        query = "UPDATE user_channels SET chat_id = %s WHERE username = %s"
        print("xd")
        self.cursor.execute(query, (channel_id, username))
        self.conn.commit()
        if self.cursor.rowcount > 0:
            print(f"Success: {self.cursor.rowcount} row(s) affected.")
        else:
            print("No rows were updated.")