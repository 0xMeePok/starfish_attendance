import mysql.connector
from functools import wraps
from config import DB_CONFIG, BOT_TOKEN

def with_db_connection(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        self.conn = mysql.connector.connect(**DB_CONFIG)
        self.cursor = self.conn.cursor()
        try:
            result = func(self, *args, **kwargs)
        finally:
            self.cursor.close()
            self.conn.close()
        return result
    return wrapper

class StarfishDB:
    def __init__(self):
        """Initializes the StarfishDB class."""
        self.token = BOT_TOKEN
        self.conn, self.cursor = None, None
    
    @with_db_connection
    def user_exists(self, username):
        """Check if a user exists."""
        query = "SELECT EXISTS(SELECT 1 FROM user_channels WHERE username = %s)"
        self.cursor.execute(query, (username,))
        return self.cursor.fetchone()[0]

    @with_db_connection
    def update_channel_id(self, username, channel_id):
        """Sets the channel ID for a user."""
        query = "UPDATE user_channels SET channel_id = %s WHERE username = %s"
        self.cursor.execute(query, (channel_id, username))
        self.conn.commit()
    
    @with_db_connection
    def get_channel_id(self, username):
        """Queries a user from the database."""
        query = "SELECT channel_id FROM user_channels WHERE username = %s"
        self.cursor.execute(query, (username,))
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    @with_db_connection
    def update_reason(self, username, reason):
        """Add a reason for being late."""
        query = """
        UPDATE user_channels 
        SET reason_for_late = %s,
            last_updated = CURRENT_TIMESTAMP 
        WHERE username = %s
        """
        self.cursor.execute(query, (reason, username))
        self.conn.commit()

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