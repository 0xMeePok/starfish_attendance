# from telegram.bot_manager import BotManager
from flask import (
    Flask,
    render_template,
    jsonify,
    request,
    redirect,
    url_for,
    flash,
    make_response,
    render_template,
    session,
    get_flashed_messages,
    send_file,
)
import mysql.connector
import random
import string
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pandas as pd
import os
import csv
import io
import logging
from io import StringIO
from werkzeug.security import generate_password_hash, check_password_hash
import sys
import atexit
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from mysql.connector import Error as MySQLConnectorError
import time
import requests
from zipfile import ZipFile

TELEGRAM_DIR = os.path.join(os.path.dirname(__file__), "telegram")
sys.path.append(TELEGRAM_DIR)



# Load environment variables from the .env file
load_dotenv()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback_secret_key")

# Directory to save uploaded files
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


# Initialize scheduler
scheduler = BackgroundScheduler()
scheduler.start()

import telebot
from threading import Thread

# Initialize bot with your token
bot = telebot.TeleBot(os.getenv('BOT_TOKEN'), parse_mode="html")
bot_instance = None

# When user uses /start command
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    username = message.chat.username
    if username:
        username = f"@{username}"
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Update the channel ID in user_channels table
            cursor.execute(
                "INSERT INTO user_channels (username, chat_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE chat_id = %s",
                (username, chat_id, chat_id)
            )
            conn.commit()
            bot.reply_to(message, f"You have been verified as {username}.")
        except Exception as e:
            logger.error(f"Error in start command: {e}")
        finally:
            cursor.close()
            conn.close()
    else:
        bot.reply_to(message, "Please set a username in your Telegram settings.")

# Route for sending messages via webhook
@app.route('/send_message', methods=['POST'])
def send_message():
    data = request.json
    username = data.get('username')
    message_text = data.get('message')
    
    if not username or not message_text:
        return jsonify({"error": "Missing username or message"}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get chat_id for the user
        cursor.execute("SELECT chat_id FROM user_channels WHERE username = %s", (username,))
        result = cursor.fetchone()
        
        if result:
            chat_id = result[0]
            # Send message
            message = bot.send_message(chat_id, message_text)
            # Register next step handler for response
            bot.register_next_step_handler(message, handle_attendance_response)
            return jsonify({"status": "success"}), 200
        else:
            return jsonify({"error": "User not found"}), 404
            
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

def handle_attendance_response(message):
    """First handler: Process yes/no response about attending class"""
    chat_id = message.chat.id
    username = f"@{message.chat.username}" if message.chat.username else None
    response = message.text.strip().lower()
    
    if not username:
        bot.send_message(chat_id, "Please set a username in Telegram settings.")
        return
        
    # Check if response is clear yes/no
    if response in ['yes', 'y', 'yeah', 'yep']:
        bot.send_message(chat_id, "Please provide your reason for being late.")
        bot.register_next_step_handler(message, handle_late_reason)
    elif response in ['no', 'n', 'nope', 'cant', "can't", 'cannot']:
        bot.send_message(chat_id, "Please provide your reason for absence.")
        bot.register_next_step_handler(message, handle_absent_reason)
    else:
        bot.send_message(chat_id, "Please respond with 'yes' or 'no' if you're coming to class today.")
        bot.register_next_step_handler(message, handle_attendance_response)

def handle_late_reason(message):
    """Handle reason for being late"""
    chat_id = message.chat.id
    username = f"@{message.chat.username}" if message.chat.username else None
    reason = message.text.strip()
    
    update_attendance_records(username, "Late", reason)
    bot.send_message(chat_id, "Thank you, your late attendance and reason have been recorded for all today's classes.")

def handle_absent_reason(message):
    """Handle reason for being absent"""
    chat_id = message.chat.id
    username = f"@{message.chat.username}" if message.chat.username else None
    reason = message.text.strip()
    
    update_attendance_records(username, "Absent with VR", reason)
    bot.send_message(chat_id, "Thank you, your absence and reason have been recorded for all today's classes.")

def update_attendance_records(username, status, reason):
    """Update attendance for all classes today for the student"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get today's date
        today = datetime.now().date()
        
        # Get all classes for the student today
        cursor.execute("""
            SELECT DISTINCT c.ClassID, s.StudentID 
            FROM classes c 
            JOIN studentsubjects ss ON c.SubjectID = ss.SubjectID
            JOIN student s ON ss.StudentID = s.StudentID
            WHERE DATE(c.ClassDate) = %s 
            AND s.TelegramUsername = %s
        """, (today, username))
        
        class_info = cursor.fetchall()
        
        if class_info:
            # Update attendance for all classes
            for class_id, student_id in class_info:
                cursor.execute("""
                    INSERT INTO attendance (StudentID, ClassID, AttendanceStatus, Reason, TimeAttended)
                    VALUES (%s, %s, %s, %s, CURRENT_TIME())
                    ON DUPLICATE KEY UPDATE 
                    AttendanceStatus = VALUES(AttendanceStatus),
                    Reason = VALUES(Reason),
                    TimeAttended = VALUES(TimeAttended)
                """, (student_id, class_id, status, reason))
            
            conn.commit()
    
    except Exception as e:
        logger.error(f"Error updating attendance records: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def run_bot():
    """Function to run the bot polling in a separate thread"""
    while True:
        try:
            logger.info("Starting bot polling...")
            bot.polling(none_stop=True, timeout=60)
        except Exception as e:
            logger.error(f"Bot polling error: {e}")
            time.sleep(10)  # Wait before retrying

def init_bot():
    """Initialize the Telegram bot"""
    global bot_instance
    if bot_instance is None:
        try:
            bot_thread = Thread(target=run_bot)
            bot_thread.daemon = True
            bot_thread.start()
            bot_instance = bot_thread
            logger.info("Bot thread started")
            
            # Schedule the attendance check
            scheduler.add_job(
                check_student_attendance,
                'cron',
                hour=10,
                minute=15,
                id='attendance_check',
                replace_existing=True
            )
        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")

@app.before_request
def before_request():
    """Initialize bot before first request if not already initialized"""
    global bot_instance
    if bot_instance is None:
        init_bot()

# Add cleanup handler
atexit.register(lambda: bot.stop_polling() if bot_instance else None)

# Modify your check_attendance function in the AttendanceBot class
# def check_student_attendance():
#     """Check attendance for students at 10:15 AM"""
#     current_time = datetime.now().time()
#     target_time = time(10, 15)  # 10:15 AM
    
#     if current_time.hour == target_time.hour and current_time.minute == target_time.minute:
#         try:
#             conn = get_db_connection()
#             cursor = conn.cursor()
            
#             # Get students who haven't marked attendance for today's first class
#             today = datetime.now().date()
#             cursor.execute("""
#                 SELECT DISTINCT s.TelegramUsername, uc.chat_id
#                 FROM student s
#                 JOIN studentsubjects ss ON s.StudentID = ss.StudentID
#                 JOIN classes c ON ss.SubjectID = c.SubjectID
#                 LEFT JOIN attendance a ON s.StudentID = a.StudentID AND c.ClassID = a.ClassID
#                 LEFT JOIN user_channels uc ON s.TelegramUsername = uc.username
#                 WHERE DATE(c.ClassDate) = %s
#                 AND (a.AttendanceStatus IS NULL OR a.AttendanceStatus = 'Absent')
#                 AND s.TelegramUsername IS NOT NULL
#                 AND uc.chat_id IS NOT NULL
#             """, (today,))
            
#             absent_students = cursor.fetchall()
            
#             for student in absent_students:
#                 username, chat_id = student
#                 try:
#                     message = bot.send_message(
#                         chat_id,
#                         "Are you coming to class today? Please reply 'yes' or 'no'."
#                     )
#                     bot.register_next_step_handler(message, handle_attendance_response)
#                 except Exception as e:
#                     logger.error(f"Failed to send message to {username}: {e}")
            
#         except Exception as e:
#             logger.error(f"Error in attendance check: {e}")
#         finally:
#             cursor.close()
#             conn.close()

def check_student_attendance():
    """Check attendance for students (test version without time check)"""
    try:
        logger.info("Running attendance check...")
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get students who haven't marked attendance for today's first class
        today = datetime.now().date()
        cursor.execute("""
            SELECT DISTINCT s.TelegramUsername, uc.chat_id
            FROM student s
            JOIN studentsubjects ss ON s.StudentID = ss.StudentID
            JOIN classes c ON ss.SubjectID = c.SubjectID
            LEFT JOIN attendance a ON s.StudentID = a.StudentID AND c.ClassID = a.ClassID
            LEFT JOIN user_channels uc ON s.TelegramUsername = uc.username
            WHERE DATE(c.ClassDate) = %s
            AND (a.AttendanceStatus IS NULL OR a.AttendanceStatus = 'Absent')
            AND s.TelegramUsername IS NOT NULL
            AND uc.chat_id IS NOT NULL
        """, (today,))
        
        absent_students = cursor.fetchall()
        logger.info(f"Found {len(absent_students)} students to check")
        
        for student in absent_students:
            username, chat_id = student
            logger.info(f"Sending message to {username}")
            try:
                message = bot.send_message(
                    chat_id,
                    "Are you coming to class today? Please reply with your reason if you will be absent or late."
                )
                bot.register_next_step_handler(message, handle_attendance_response)
                logger.info(f"Message sent successfully to {username}")
            except Exception as e:
                logger.error(f"Failed to send message to {username}: {e}")
            
    except Exception as e:
        logger.error(f"Error in attendance check: {e}")
    finally:
        cursor.close()
        conn.close()

# Add a test endpoint to trigger the check manually
@app.route('/test_attendance_check')
def test_attendance_check():
    try:
        check_student_attendance()
        return jsonify({"status": "success", "message": "Attendance check triggered"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Add the scheduler job
scheduler.add_job(
    check_student_attendance,
    'cron',
    hour=10,
    minute=15,
    id='attendance_check'
)


# Database connection details using environment variables
db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
}


# Custom handler for 404 Not Found
@app.errorhandler(404)
def page_not_found(e):
    return (
        render_template(
            "error.html", error="The page you are looking for does not exist."
        ),
        404,
    )


# Custom handler for 500 Internal Server Error


@app.errorhandler(500)
def internal_server_error(e):
    return render_template("error.html", error="Internal Server Error."), 500


"""
# Custom handler for other exceptions
@app.errorhandler(Exception)
def handle_exception(e):
    # Log the error details (only on the server side, not to the user)
    app.logger.error(f"Server error: {str(e)}")
    
    # Return a generic error message
    return render_template('error.html', error="Internal Server Error."), 500
"""


def get_db_connection():
    """Establish a new database connection."""
    connection = mysql.connector.connect(**db_config)
    return connection


"""
Creation of Classes to map:


"""


@app.route("/create_subject_class", methods=["GET", "POST"])
def create_subject_class():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    if request.method == "POST":
        subject_id = request.form.get("subject_id")
        new_subject = request.form.get("new_subject")
        class_date = request.form.get("class_date")

        try:
            # If a new subject is provided, insert it
            if new_subject:
                cursor.execute(
                    "INSERT INTO subject (SubjectName) VALUES (%s)", (new_subject,)
                )
                conn.commit()
                subject_id = cursor.lastrowid

            # Insert the new class
            cursor.execute(
                "INSERT INTO classes (ClassDate, SubjectID) VALUES (%s, %s)",
                (class_date, subject_id),
            )
            conn.commit()
            new_class_id = cursor.lastrowid

            # Check for students already enrolled in this subject
            cursor.execute(
                "SELECT StudentID FROM studentsubjects WHERE SubjectID = %s",
                (subject_id,),
            )
            enrolled_students = cursor.fetchall()

            # If students are enrolled, insert their attendance records for the new class
            if enrolled_students:
                for student in enrolled_students:
                    cursor.execute(
                        """
                        INSERT INTO attendance (StudentID, ClassID, AttendanceStatus)
                        VALUES (%s, %s, 'Absent')
                    """,
                        (student[0], new_class_id),
                    )
                conn.commit()

        except mysql.connector.Error as err:
            conn.rollback()
            flash(f"Error creating class: {err}", "error")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("create_subject_class"))

    # Fetch existing subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM subject ORDER BY SubjectName")
    subjects = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("create_subject_class.html", subjects=subjects)


def generate_channel_id():
    return "channel_" + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=6)
    )


@app.route("/enroll_student", methods=["GET", "POST"])
def enroll_student():
    if request.method == "POST":
        student_name = request.form["student_name"]
        email = request.form["email"]
        phone_number = request.form["phone_number"]
        social_worker_email = request.form["social_worker_email"]
        social_worker_phone = request.form["social_worker_phone"]
        parent_email = request.form["parent_email"]
        parent_phone = request.form["parent_phone"]
        telegram_username = request.form["telegram_username"]

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Generate a unique channel_id
            channel_id = generate_channel_id()
            while True:
                cursor.execute(
                    "SELECT COUNT(*) FROM student WHERE ChannelID = %s", (channel_id,)
                )
                if cursor.fetchone()[0] == 0:
                    break
                channel_id = generate_channel_id()

            # Insert the new student into the database
            insert_query = """
            INSERT INTO student (StudentName, Email, PhoneNumber, SocialWorkerEmail, SocialWorkerPhone, ParentEmail, ParentPhone, TelegramUsername, ChannelID)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(
                insert_query,
                (
                    student_name,
                    email,
                    phone_number,
                    social_worker_email,
                    social_worker_phone,
                    parent_email,
                    parent_phone,
                    telegram_username,
                    channel_id,
                ),
            )
            conn.commit()

            flash("Student enrolled successfully!", "success")
            return redirect(url_for("enroll_student"))
        except mysql.connector.Error as err:
            flash(f"Error enrolling student: {err}", "error")
        finally:
            cursor.close()
            conn.close()

    return render_template("enroll_student.html")


@app.route("/upload_student_enrollment", methods=["POST"])
def upload_student_enrollment():
    if "file" not in request.files:
        flash("No file part", "error")
        return redirect(url_for("enroll_student"))

    file = request.files["file"]

    if file.filename == "":
        flash("No selected file", "error")
        return redirect(url_for("enroll_student"))

    if file and file.filename.endswith(".csv"):
        try:
            # Read the CSV file
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.reader(stream)
            next(csv_reader)  # Skip header row if present

            conn = get_db_connection()
            cursor = conn.cursor()

            for row in csv_reader:
                if len(row) != 8:
                    flash(f"Invalid row in CSV: {row}. Expected 8 fields.", "error")
                    continue

                (
                    student_name,
                    email,
                    phone_number,
                    social_worker_email,
                    social_worker_phone,
                    parent_email,
                    parent_phone,
                    telegram_username,
                ) = row

                # Generate a unique channel_id
                channel_id = generate_channel_id()
                while True:
                    cursor.execute(
                        "SELECT COUNT(*) FROM student WHERE ChannelID = %s",
                        (channel_id,),
                    )
                    if cursor.fetchone()[0] == 0:
                        break
                    channel_id = generate_channel_id()

                # Insert the new student into the database
                insert_query = """
                INSERT INTO student (StudentName, Email, PhoneNumber, SocialWorkerEmail, SocialWorkerPhone, ParentEmail, ParentPhone, TelegramUsername, ChannelID)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(
                    insert_query,
                    (
                        student_name,
                        email,
                        phone_number,
                        social_worker_email,
                        social_worker_phone,
                        parent_email,
                        parent_phone,
                        telegram_username,
                        channel_id,
                    ),
                )

            conn.commit()
            cursor.close()
            conn.close()

            flash("Students enrolled successfully from CSV!", "success")
        except Exception as e:
            flash(f"Error processing CSV file: {str(e)}", "error")
    else:
        flash("Invalid file type. Please upload a CSV file.", "error")

    return redirect(url_for("enroll_student"))


@app.route("/enroll_classes", methods=["GET", "POST"])
def enroll_classes():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    students = cursor.fetchall()

    # Initialize an empty subjects list
    subjects = []

    if request.method == "POST":
        student_id = request.form["student_id"]

        # Fetch subjects that the student is NOT enrolled in
        cursor.execute(
            """
            SELECT s.SubjectID, s.SubjectName 
            FROM subject s
            WHERE s.SubjectID NOT IN (
                SELECT ss.SubjectID 
                FROM studentsubjects ss 
                WHERE ss.StudentID = %s
            )
        """,
            (student_id,),
        )
        subjects = cursor.fetchall()

        if "subject_id" in request.form:
            subject_id = request.form["subject_id"]

            # Enroll the student in the subject (Insert into StudentSubjects)
            cursor.execute(
                """
                INSERT INTO studentsubjects (StudentID, SubjectID)
                VALUES (%s, %s)
            """,
                (student_id, subject_id),
            )

            # Get all classes for the given SubjectID
            cursor.execute(
                """
                SELECT ClassID FROM classes WHERE SubjectID = %s
            """,
                (subject_id,),
            )
            classes = cursor.fetchall()

            # Create attendance records for the student for each class
            for class_record in classes:
                cursor.execute(
                    """
                    INSERT INTO attendance (StudentID, ClassID, AttendanceStatus)
                    VALUES (%s, %s, 'Absent')
                """,
                    (student_id, class_record["ClassID"]),
                )

            conn.commit()
            return redirect(url_for("enroll_classes"))

    cursor.close()
    conn.close()

    return render_template("enroll_classes.html", students=students, subjects=subjects)


@app.route("/get_unenrolled_subjects/<int:student_id>")
def get_unenrolled_subjects(student_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch subjects that the student is NOT enrolled in
    cursor.execute(
        """
        SELECT s.SubjectID, s.SubjectName 
        FROM subject s
        WHERE s.SubjectID NOT IN (
            SELECT ss.SubjectID 
            FROM studentsubjects ss 
            WHERE ss.StudentID = %s
        )
    """,
        (student_id,),
    )
    subjects = cursor.fetchall()

    cursor.close()
    conn.close()

    return jsonify(subjects)


# Attendance related functions
"""
Attendance related functions and routes below
Allows the marking of individual class
Allows the viewing of all attendance


"""


@app.route("/overall_attendance")
def overall_attendance():
    logging.debug("Entering overall_attendance route")
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch all student names
        cursor.execute("SELECT DISTINCT StudentName FROM student ORDER BY StudentName")
        all_students = [row["StudentName"] for row in cursor.fetchall()]

        # Fetch all subject names
        cursor.execute("SELECT DISTINCT SubjectName FROM subject ORDER BY SubjectName")
        all_subjects = [row["SubjectName"] for row in cursor.fetchall()]

        query = """
        SELECT 
            s.StudentID,
            s.StudentName,
            c.ClassID,
            c.ClassDate,
            sub.SubjectID,
            sub.SubjectName,
            a.AttendanceStatus,
            a.TimeAttended,
            a.Reason
        FROM 
            student s
        JOIN 
            attendance a ON s.StudentID = a.StudentID
        JOIN 
            classes c ON a.ClassID = c.ClassID
        JOIN
            subject sub ON c.SubjectID = sub.SubjectID
        ORDER BY 
            c.ClassDate DESC, s.StudentName, sub.SubjectName
        """

        logging.debug(f"Executing query: {query}")
        cursor.execute(query)
        attendance_data = cursor.fetchall()
        logging.debug(f"Fetched {len(attendance_data)} records")

        # Format the datetime objects
        for row in attendance_data:
            row["ClassDate"] = row["ClassDate"].strftime("%Y-%m-%d")
            if isinstance(row["TimeAttended"], timedelta):
                total_seconds = int(row["TimeAttended"].total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                row["TimeAttended"] = f"{hours:02d}:{minutes:02d}"
            elif row["TimeAttended"] is None:
                row["TimeAttended"] = ""

        cursor.close()
        conn.close()

        logging.debug("Rendering attendance.html template")
        return render_template(
            "attendance.html",
            attendance_data=attendance_data,
            all_students=all_students,
            all_subjects=all_subjects,
        )
    except Exception as e:
        logging.error(f"Error in overall_attendance route: {str(e)}")
        return f"An error occurred: {str(e)}", 500


@app.route("/update_attendance", methods=["POST"])
def update_attendance():
    data = request.json
    logging.info(f"Received data: {data}")

    # Ensure the received data is a dictionary
    if not isinstance(data, dict):
        logging.error("Invalid data format: Expected a dictionary")
        return jsonify({"status": "error", "message": "Invalid data format"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Accessing data as a dictionary
        student_id = data["StudentID"]
        class_id = data["ClassID"]
        new_status = data["AttendanceStatus"]
        # Get the time from the request
        time_attended = data.get("TimeAttended", "")
        reason = data.get("Reason", "")

        # Fetch the current status of the student for the specific class
        cursor.execute(
            """
            SELECT AttendanceStatus, TimeAttended FROM attendance
            WHERE StudentID = %s AND ClassID = %s
        """,
            (student_id, class_id),
        )
        current_record = cursor.fetchone()

        if not current_record:
            logging.error(
                f"No existing attendance record found for StudentID={student_id}, ClassID={class_id}"
            )
            return (
                jsonify({"status": "error", "message": "No existing record found"}),
                404,
            )

        current_status, current_time_attended = current_record

        # Check if time_attended was provided in the request
        if not time_attended:
            # Only update TimeAttended if the status changes to 'Present' and was not 'Present' before
            if current_status != "Present" and new_status == "Present":
                time_attended = datetime.now().strftime(
                    "%H:%M:%S"
                )  # Set to current time
                logging.info(f"TimeAttended updated to current time: {time_attended}")
            else:
                time_attended = current_time_attended  # Retain the current time
        else:
            logging.info(f"TimeAttended manually updated to: {time_attended}")

        logging.info(
            f"Updating record: StudentID={student_id}, ClassID={class_id}, Status={new_status}, Time={time_attended}, Reason={reason}"
        )

        # Update the attendance record
        update_query = """
        UPDATE attendance
        SET AttendanceStatus = %s, TimeAttended = %s, Reason = %s
        WHERE StudentID = %s AND ClassID = %s
        """
        cursor.execute(
            update_query, (new_status, time_attended, reason, student_id, class_id)
        )
        logging.info(f"Rows affected: {cursor.rowcount}")

        conn.commit()
        logging.info("Database committed successfully")
        return jsonify({"status": "success"})
    except Exception as e:
        logging.error(f"Error updating attendance: {str(e)}")
        conn.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()
        logging.info("Database connection closed")


@app.route("/update_remark_reason", methods=["POST"])
def update_remark_reason():
    data = request.json
    class_id = data["class_id"]
    student_id = data["student_id"]
    remark = data.get("remark")
    reason = data.get("reason")

    conn = get_db_connection()
    cursor = conn.cursor()

    update_fields = []
    update_values = []

    if remark is not None:
        update_fields.append("Remark = %s")
        update_values.append(remark)

    if reason is not None:
        update_fields.append("Reason = %s")
        update_values.append(reason)

    update_values.extend([class_id, student_id])

    if update_fields:
        update_query = f"""
        UPDATE Attendance
        SET {', '.join(update_fields)}
        WHERE ClassId = %s AND StudentId = %s
        """
        cursor.execute(update_query, update_values)
        conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status": "success"})


@app.route("/attendance/search", methods=["GET"])
def search_attendance():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Base query to retrieve all classes
    base_query = """
    SELECT ClassId, ClassName, Date FROM Classes
    """

    search_query = base_query
    query_params = []

    # Get the search parameters
    class_id = request.args.get("class_id", None)
    class_name = request.args.get("class_name", None)
    date = request.args.get("date", None)

    # Build the search query based on provided parameters
    if class_id:
        search_query += " WHERE ClassId LIKE %s"
        query_params.append(f"%{class_id}%")

    if class_name:
        if "WHERE" in search_query:
            search_query += " AND ClassName LIKE %s"
        else:
            search_query += " WHERE ClassName LIKE %s"
        query_params.append(f"%{class_name}%")

    if date:
        if "WHERE" in search_query:
            search_query += " AND DATE(Date) = %s"
        else:
            search_query += " WHERE DATE(Date) = %s"
        query_params.append(date)

    # Execute the query
    cursor.execute(search_query, query_params)
    classes = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template("search_attendance.html", classes=classes)


@app.route("/api/class-attendance", methods=["GET"])
def class_attendance():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        # Get the oldest and latest class records
        date_range_query = "SELECT MIN(ClassDate), MAX(ClassDate) FROM classes"
        cursor.execute(date_range_query)
        oldest_class_date, latest_class_date = cursor.fetchone()

        logging.debug(
            f"Oldest class date: {oldest_class_date}, Latest class date: {latest_class_date}"
        )

        query = """
        SELECT 
            DATE(c.ClassDate) as DateString,
            SUM(CASE WHEN a.AttendanceStatus = 'Present' THEN 1 ELSE 0 END) AS PresentCount,
            SUM(CASE WHEN a.AttendanceStatus = 'Late' THEN 1 ELSE 0 END) AS LateCount,
            SUM(CASE WHEN a.AttendanceStatus = 'Absent' THEN 1 ELSE 0 END) AS AbsentCount,
            SUM(CASE WHEN a.AttendanceStatus = 'Absent with VR' THEN 1 ELSE 0 END) AS AbsentVRCount
        FROM 
            classes c 
        LEFT JOIN 
            attendance a 
        ON 
            c.ClassID = a.ClassID 
        """

        if start_date and end_date:
            query += "WHERE c.ClassDate BETWEEN %s AND %s "
            query_params = (start_date, end_date)
        else:
            # If no date range is specified, use the full range of class dates
            query += "WHERE c.ClassDate BETWEEN %s AND %s "
            query_params = (oldest_class_date, latest_class_date)

        query += """
        GROUP BY 
            DATE(c.ClassDate) 
        ORDER BY 
            DateString;
        """

        logging.debug(f"Executing query: {query}")
        logging.debug(f"Query parameters: {query_params}")

        cursor.execute(query, query_params)
        results = cursor.fetchall()

        logging.debug(f"Query results: {results}")

        formatted_results = []
        for row in results:
            formatted_results.append(
                {
                    "dateString": row[0].strftime("%Y-%m-%d"),
                    "PresentCount": row[1],
                    "LateCount": row[2],
                    "AbsentCount": row[3],
                    "AbsentVRCount": row[4],
                }
            )

        cursor.close()
        conn.close()

        response_data = {
            "data": formatted_results,
            "oldestClassDate": oldest_class_date.strftime("%Y-%m-%d"),
            "latestClassDate": latest_class_date.strftime("%Y-%m-%d"),
        }
        logging.debug(f"Response data: {response_data}")

        return jsonify(response_data)

    except Exception as e:
        logging.error(f"Error fetching attendance data: {e}")
        return jsonify({"error": "An error occurred fetching data"}), 500


@app.route("/create_marks", methods=["GET", "POST"])
def create_marks():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        subject = request.form["subject"]
        test_type = request.form["test_type"]
        term_no = request.form["term"]
        student_id = request.form["student_id"]
        if request.form.get("attend_assessment"):
            marks_obtained = float(request.form["marks_obtained"])
            total_marks = float(request.form["total_marks"])
        else:
            marks_obtained = 0
            total_marks = 0
        weightage = float(request.form["weightage"])
        # Get the checkbox value - will be 'on' if checked, None if unchecked
        is_term_test = 1 if request.form.get("is_term_test") else 0


        # Insert the marks into the database
        insert_query = """
        INSERT INTO marks (StudentID, SubjectID, TestType, MarksObtained, TotalMarks, Weightage, Term, IsTermTest)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(
            insert_query,
            (student_id, subject, test_type, marks_obtained, total_marks, weightage, term_no, is_term_test),
        )
        conn.commit()

        cursor.close()
        conn.close()

        return redirect(url_for("create_marks"))

    # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    students = cursor.fetchall()

    # Fetch all subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM subject")
    subjects = cursor.fetchall()

    cursor.close()
    conn.close()

    # Pass both students and subjects to the template
    return render_template("create_marks.html", students=students, subjects=subjects)


@app.route("/export_class_attendance", methods=["GET", "POST"])
def export_class_attendance():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM subject")
    subjects = cursor.fetchall()

    if request.method == "POST":
        selected_subject_id = request.form.get("selected_subject")
        selected_class_date = request.form.get("selected_class_date")

        # Fetch attendance data for the selected subject and class date
        cursor.execute(
            """
            SELECT student.StudentName, attendance.AttendanceStatus
            FROM attendance
            JOIN student ON attendance.StudentID = student.StudentID
            JOIN classes ON attendance.ClassID = classes.ClassID
            WHERE classes.SubjectID = %s AND classes.ClassDate = %s
        """,
            (selected_subject_id, selected_class_date),
        )
        attendance_data = cursor.fetchall()
        # Fetch the subject name to include in the filename
        cursor.execute(
            "SELECT SubjectName FROM subject WHERE SubjectID = %s",
            (selected_subject_id,),
        )
        subject_name = cursor.fetchone()[0]

        # Initialize categorized attendance dictionary for all statuses
        categorized_attendance = {
            "Present": [],
            "Late": [],
            "Absent": [],
            "Absent with VR": [],
        }

        # Categorize attendance
        for student_name, attendance_status in attendance_data:
            if attendance_status in categorized_attendance:
                categorized_attendance[attendance_status].append(student_name)

        # Create a CSV response
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(["Attendance Status", "Students"])

        # Write categorized attendance
        for status, students in categorized_attendance.items():
            writer.writerow([status, ", ".join(students)])

        output.seek(0)
        formatted_date = datetime.strptime(selected_class_date, "%Y-%m-%d").strftime(
            "%Y-%m-%d"
        )
        filename = f"{subject_name}_{formatted_date}.csv"
        # Generate a response with the CSV file for download
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        response.headers["Content-type"] = "text/csv"

        cursor.close()
        conn.close()

        return response  # This sends the CSV file as a response

    # If it's a GET request, render the form
    cursor.close()
    conn.close()
    return render_template("export_class_attendance.html", subjects=subjects)


@app.route("/get_classes", methods=["GET"])
def get_classes():
    subject_id = request.args.get("subject_id")

    if not subject_id:
        return jsonify({"error": "Subject ID is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Fetch class dates for the selected subject
        cursor.execute(
            "SELECT ClassDate FROM classes WHERE SubjectID = %s", (subject_id,)
        )
        class_dates = cursor.fetchall()

        # Create a list of class dates to return as JSON
        result = {
            "classes": [
                {"ClassDate": class_date[0].strftime("%Y-%m-%d")}
                for class_date in class_dates
            ]
        }
        return jsonify(result)

    except Exception as e:
        print(f"Error fetching class dates: {e}")
        return jsonify({"error": "Failed to fetch class dates"}), 500
    finally:
        cursor.close()
        conn.close()


@app.route("/export_marks", methods=["GET", "POST"])
def export_marks():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    students = cursor.fetchall()

    if request.method == "POST":
        selected_student_id = request.form.get("selected_student")

        # Fetch marks data for the selected student, including SubjectName
        cursor.execute(
            """
            SELECT subject.SubjectName, marks.TestType, marks.MarksObtained, marks.TotalMarks, marks.Weightage
            FROM marks
            JOIN subject ON marks.SubjectID = subject.SubjectID
            WHERE marks.StudentID = %s
        """,
            (selected_student_id,),
        )
        marks_data = cursor.fetchall()

        # Create a CSV response
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(
            ["Subject Name", "Test Type", "Marks Obtained", "Total Marks", "Weightage"]
        )

        # Write marks data
        for row in marks_data:
            writer.writerow(row)

        output.seek(0)

        # Fetch student name for filename
        cursor.execute(
            "SELECT StudentName FROM student WHERE StudentID = %s",
            (selected_student_id,),
        )
        student_name = cursor.fetchone()[0]

        # Create a filename using the student name
        filename = f"{student_name}_marks.csv"

        # Generate a response with the CSV file for download
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = f"attachment; filename={filename}"
        response.headers["Content-type"] = "text/csv"

        cursor.close()
        conn.close()

        return response  # This sends the CSV file as a response

    # If it's a GET request, render the form
    cursor.close()
    conn.close()
    return render_template("export_marks.html", students=students)


# Store user log in

# CREATE TABLE `users` (
#  `user_id` int NOT NULL AUTO_INCREMENT,
#  `username` varchar(50) NOT NULL,
#  `password` varchar(200) NOT NULL,
#  `role` int NOT NULL,
#  PRIMARY KEY (`user_id`)
# ) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    authoriseBool = False

    # login logic
    if request.method == "POST":
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "select password from users where username = %s",
                (request.form["username"],),
            )
            hashed_pwd = cursor.fetchall()

            if hashed_pwd != []:
                authoriseBool = check_password_hash(
                    hashed_pwd[0][0], request.form["password"]
                )

                if authoriseBool:
                    cursor.execute(
                        "select user_id, role from users where username = %s",
                        (request.form["username"],),
                    )
                    result = cursor.fetchone()
                    session["user_id"] = result[0]
                    session["role"] = result[1]
                    return redirect(url_for("homepage"))
                else:
                    flash("incorrect username and password, try again")
                    return redirect(url_for("login"))

            else:
                flash("incorrect username and password, try again")
                return redirect(url_for("login"))

        except mysql.connector.Error as err:
            flash(f"Error: {err}")
            conn.rollback()
            return redirect(url_for("login"))
        finally:
            cursor.close()
            conn.close()

    else:
        # by default will run this when first navigated to
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if already logged in, if yes redirect back to homepage
        if "user_id" in session and "role" in session:
            conn = get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT role FROM users WHERE user_id = %s", (session["user_id"],)
                )
                result = cursor.fetchall()

                # Check if there is any result before accessing
                if result:
                    actual_role = result[0][0]
                    if actual_role == session["role"]:
                        return redirect(url_for("homepage"))
                else:
                    flash(
                        "No user data found in the database. Please register first.",
                        "error",
                    )
                    return redirect(
                        url_for("register")
                    )  # Redirect to registration if database is empty

            except mysql.connector.Error as err:
                flash(f"Error: {err}")
                conn.rollback()

            finally:
                cursor.close()
                conn.close()

        return render_template("login.html")


@app.route("/homepage", methods=["GET", "POST"])
def homepage():
    return render_template("homepage.html")


# to edit later


@app.route("/forgetpassword")
def forgetpassword():
    return render_template("forgetpassword.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("role", None)
    flash("You have successfully logged out")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            hashed_password = generate_password_hash(request.form["password"])
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, 0)",
                (request.form["username"], hashed_password),
            )
            conn.commit()

            # Fetch the newly created user's ID and role
            cursor.execute(
                "SELECT user_id, role FROM users WHERE username = %s",
                (request.form["username"],),
            )
            result = cursor.fetchone()

            # Check if the result is not None
            if result:
                session["user_id"] = result[0]
                session["role"] = result[1]  # Store the role in the session
                flash("Registration successful!", "success")
                return redirect(url_for("homepage"))
            else:
                flash(
                    "An error occurred during registration. Please try again.", "error"
                )

        except mysql.connector.Error as err:
            flash(f"Error: {err}", "error")
            conn.rollback()
        finally:
            cursor.close()
            conn.close()

    # Check if the user is already logged in, redirect to homepage if so
    elif "user_id" in session and "role" in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT role FROM users WHERE user_id = %s", (session["user_id"],)
            )
            result = cursor.fetchone()

            # Verify if result exists and matches the session role
            if result and result[0] == session["role"]:
                return redirect(url_for("homepage"))

        except mysql.connector.Error as err:
            flash(f"Error: {err}", "error")
        finally:
            cursor.close()
            conn.close()

    return render_template("register.html")


@app.route("/error", methods=["GET", "POST"])
def errorPage(err):
    return render_template("error.html", error=err)


@app.route("/generate_report", methods=["GET", "POST"])
def generate_report():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    students = cursor.fetchall()

    # Get years from classes
    cursor.execute("SELECT ClassDate FROM classes")
    classDates = cursor.fetchall()
    years = [row[0].year for row in classDates]

    try:
        max_year = max(years)
        min_year = min(years)
    except:
        # Handle case when there are no attendance records
        return render_template("generate_report.html", 
                             students=students, 
                             years=[], 
                             error_message="Database does NOT contain ANY class information or test scores, therefore unable to generate reports of students")

    years = list(range(min_year, max_year + 1))

    if request.method == "POST":
        selected_report = request.form.get("selected_report")
        selected_year = request.form.get("selected_year")
        selected_student_id = request.form.get("selected_student")
        selected_term = request.form.get("selected_term")

        try:
            if selected_report == "1":  # Progress Report
                # Get student data
                name, marks_data, attendanceByStatus, year = retrieveProgressDetails(selected_student_id, selected_year, selected_term)
            else:  # Overall Report
                # Get student data
                name, marks_data, attendanceByStatus, year = retrieveDetails(selected_student_id, selected_year)

            # Check for missing core subjects
            required_subjects = ['English', 'Math', 'Science']
            missing_subjects = [subject for subject in required_subjects if subject not in marks_data]

            if missing_subjects:
                if selected_report == "1":
                    missing_subjects_str = ", ".join(missing_subjects)
                    # Get student name
                    cursor.execute("SELECT StudentName FROM student WHERE StudentID = %s", (selected_student_id,))
                    student_name = cursor.fetchone()[0]  # This gets just the name string
                    flash(f"Warning: No relevant data found for the following subjects: {missing_subjects_str}, Term {selected_term}, Year {selected_year}, Student {student_name}", "warning")
                    flash(f"Ensure that you have added the Term Test Results for this student in that Term in Add Result Page", "warning")
                    return redirect(url_for('generate_report'))
                else:
                    missing_subjects_str = ", ".join(missing_subjects)
                    # Get student name
                    cursor.execute("SELECT StudentName FROM student WHERE StudentID = %s", (selected_student_id,))
                    student_name = cursor.fetchone()[0]  # This gets just the name string
                    flash(f"Warning: No relevant data found for the following subjects: {missing_subjects_str}, Year {selected_year}, Student {student_name}", "warning")
                    flash(f"Ensure that you have added at least 1 assessment for this student in Add Result Page", "warning")
                    return redirect(url_for('generate_report'))

            data = {
                "name": name,
                "marks": marks_data,
                "attendanceByStatus": attendanceByStatus,
                "year": year
            }

            if selected_report == "1":
                # Fetch term dates for progress report
                cursor.execute("""
                    SELECT start_date, end_date 
                    FROM term 
                    WHERE id = %s
                """, (selected_term,))
                term_dates = cursor.fetchone()
                
                if term_dates:
                    data["term"] = {
                        "number": selected_term,
                        "start_date": term_dates[0].strftime('%d/%m/%y'),
                        "end_date": term_dates[1].strftime('%d/%m/%y')
                    }
                return render_template("report_progress_template.html", data=data, now=datetime.now())
            else:
                return render_template("report_overall_template.html", data=data, now=datetime.now())

        except Exception as e:
            flash(f"Error generating report: {str(e)}", "error")
            return redirect(url_for('generate_report'))

    cursor.close()
    conn.close()
    return render_template("generate_report.html", students=students, years=years)

def retrieveProgressDetails(student_id, year, term):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Modify this query to fetch just the name string instead of a tuple
        cursor.execute(
            """
            SELECT StudentName
            FROM student
            WHERE StudentID = %s
            """,
            (student_id,)
        )
        
        # Fetch the single name value instead of all results
        name = cursor.fetchone()[0]  # This gets just the name string
        
    except Exception as e:
        logger.error(f"Error fetching student name: {e}")
        raise

    # Execute the SQL query, to extract only thoses Term Test defined
    try:
        cursor.execute(
            """
            SELECT DISTINCT StudentID, SubjectName, MarksObtained, TotalMarks, Weightage
            FROM (
                SELECT m.StudentID, SubjectName, m.MarksObtained, m.TotalMarks, m.Weightage, c.classDate
                FROM attendance a
                JOIN classes c ON a.classID = c.classID
                JOIN marks m ON c.subjectID = m.SubjectID AND m.Term = %s AND m.IsTermTest = 1
                JOIN subject s on s.SubjectID = m.subjectID
            ) AS StudentMarks
            WHERE StudentID = %s
            AND YEAR(classDate) = %s
        """,
            (term, student_id, year)
        )
        # Fetch all results
        results = cursor.fetchall()
        
        marks_data = {}

        for row in results:
            student_id, subject, marks_obtained, total_marks, weightage = row

            if subject not in marks_data:
                if marks_obtained == 0 and total_marks == 0:
                    marks_data[subject] = ['-', '-', 'Absent']
                else:
                    try:
                        percentage = (marks_obtained / total_marks * 100) if total_marks > 0 else 0
                        marks_data[subject] = [marks_obtained, total_marks, get_grade(percentage)]
                    except:
                        marks_data[subject] = [0, 0, 'N/A']

        # Calculate average grade safely
        if marks_data and any(isinstance(mark, list) for mark in marks_data.values()):
            total_percentage = 0
            num_subjects = 0
            num_present_subjects = 0

            for mark in marks_data.values():
                if isinstance(mark, list):
                    if mark[0] == 0 and mark[1] == 0:  # Absent case
                        num_subjects += 1
                    else:
                        try:
                            if mark[1] > 0:  # Check for non-zero denominator
                                total_percentage += round(mark[0]/mark[1]*100, 2)
                                num_subjects += 1
                                num_present_subjects += 1
                        except:
                            continue

            # Calculate average only if there are valid subjects
            if num_present_subjects > 0:
                average_percentage = round(total_percentage / num_subjects, 2)
            else:
                average_percentage = 0

            marks_data['total'] = [average_percentage, get_grade(average_percentage)]
        else:
            marks_data['total'] = [0, get_grade(0)]


         # Get term dates
        cursor.execute("""
            SELECT start_date, end_date 
            FROM term 
            WHERE id = %s
        """, (term,))
        term_dates = cursor.fetchone()
        
        if term_dates:
            start_date, end_date = term_dates
        else:
            start_date = end_date = None

        cursor.execute(
            """
            SELECT a.AttendanceStatus, COUNT(*) AS numOfAttendance 
            FROM attendance a
            JOIN classes c ON a.ClassID = c.ClassID 
            WHERE a.StudentID = %s AND YEAR(c.ClassDate) = %s AND classDate BETWEEN %s AND %s
            GROUP BY a.AttendanceStatus
        """,
            (student_id, year, start_date, end_date),
        )

        attendanceByStatus = cursor.fetchall()
        attendanceByStatus = dict(attendanceByStatus)

        totalSum = sum(attendanceByStatus.values())

        if "Absent with VR" not in attendanceByStatus:
            attendanceByStatus["Absent with VR"] = 0

        if "Late" not in attendanceByStatus:
            attendanceByStatus["Late"] = 0

        if "Present" not in attendanceByStatus:
            attendanceByStatus["Present"] = 0

        attendanceByStatus["total"] = totalSum

        cursor.close()
        conn.close()
        return name, marks_data, attendanceByStatus, year

    except Exception as e:
        print(f"An error occurred: {e}")

def retrieveDetails(student_id, year):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            """
            SELECT StudentName
            FROM student
            WHERE StudentID = %s;
        """,
            (student_id,),
        )

        name = cursor.fetchall()

    except Exception as e:
        print(f"An error occurred: {e}")

    # Execute the SQL query
    try:
        cursor.execute(
            """
            SELECT DISTINCT StudentID, SubjectName, MarksObtained, TotalMarks, Weightage
            FROM (
                SELECT m.StudentID, SubjectName, m.MarksObtained, m.TotalMarks, m.Weightage, c.classDate
                FROM attendance a
                JOIN classes c ON a.classID = c.classID
                JOIN marks m ON c.subjectID = m.SubjectID
                JOIN subject s on s.SubjectID = m.subjectID
            ) AS StudentMarks
            WHERE StudentID = %s
            AND YEAR(classDate) = %s;
        """,
            (student_id, year),
        )
        # Fetch all results
        results = cursor.fetchall()

    except Exception as e:
        print(f"An error occurred: {e}")

    # Initialize variables to calculate overall marks
    marks_data = {}

    for row in results:
        student_id, subject, marks_obtained, total_marks, weightage = row

        try:
            if subject not in marks_data:
                if marks_obtained == 0 or total_marks == 0:
                    marks_data[subject] = 0
                else:
                    marks_data[subject] = (marks_obtained / total_marks) * weightage
            else:
                if marks_obtained == 0 or total_marks == 0:
                    marks_data[subject] += 0
                else:
                    marks_data[subject] += (marks_obtained / total_marks) * weightage
        except:
            if subject not in marks_data:
                marks_data[subject] = 0

    # Convert marks to grades safely
    for n in marks_data:
        marks_data[n] = [marks_data[n], get_grade(marks_data[n])]

    # Calculate average grade safely
    if marks_data:
        try:
            total_marks = sum(mark[0] for mark in marks_data.values() if isinstance(mark, list))
            num_subjects = len([mark for mark in marks_data.values() if isinstance(mark, list)])
            average_mark = total_marks / num_subjects if num_subjects > 0 else 0
            marks_data['total'] = [average_mark, get_grade(average_mark)]
        except:
            marks_data['total'] = [0, get_grade(0)]
    else:
        marks_data['total'] = [0, get_grade(0)]

    cursor.execute(
        """
        SELECT a.AttendanceStatus, COUNT(*) AS numOfAttendance 
        FROM attendance a
        JOIN classes c ON a.ClassID = c.ClassID 
        WHERE a.StudentID = %s AND YEAR(c.ClassDate) = %s 
        GROUP BY a.AttendanceStatus
    """,
        (student_id, year),
    )

    attendanceByStatus = cursor.fetchall()
    attendanceByStatus = dict(attendanceByStatus)

    totalSum = sum(attendanceByStatus.values())

    if "Absent with VR" not in attendanceByStatus:
        attendanceByStatus["Absent with VR"] = 0

    if "Late" not in attendanceByStatus:
        attendanceByStatus["Late"] = 0

    if "Present" not in attendanceByStatus:
        attendanceByStatus["Present"] = 0

    attendanceByStatus["total"] = totalSum

    cursor.close()
    conn.close()

    return name, marks_data, attendanceByStatus, year


def get_grade(score):
    if 75 <= score <= 100:
        return "A"
    elif 70 <= score <= 74:
        return "B"
    elif 60 <= score <= 69:
        return "C"
    elif 50 <= score <= 59:
        return "D"
    elif 0 <= score <= 49:
        return "E"


@app.route("/export_subject_attendance", methods=["GET", "POST"])
def export_subject_attendance():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM subject")
    subjects = cursor.fetchall()

    if request.method == "POST":
        selected_subject_id = request.form.get("subject_id")

        # Fetch all classes and dates for the selected subject
        cursor.execute(
            """
            SELECT DISTINCT ClassID, ClassDate 
            FROM classes 
            WHERE SubjectID = %s
            ORDER BY ClassDate
        """,
            (selected_subject_id,),
        )
        classes = cursor.fetchall()

        # Extract just the dates from classes
        class_dates = [cls[1].strftime("%Y-%m-%d") for cls in classes]

        # Fetch students enrolled in the subject
        cursor.execute(
            """
            SELECT DISTINCT s.StudentID, s.StudentName 
            FROM student s
            JOIN studentsubjects ss ON s.StudentID = ss.StudentID
            WHERE ss.SubjectID = %s
        """,
            (selected_subject_id,),
        )
        students = cursor.fetchall()

        # Fetch attendance for each student for the classes in this subject
        attendance_data = {}
        for student_id, _ in students:
            cursor.execute(
                """
                SELECT a.ClassID, a.AttendanceStatus
                FROM attendance a
                JOIN classes c ON a.ClassID = c.ClassID
                WHERE a.StudentID = %s AND c.SubjectID = %s
            """,
                (student_id, selected_subject_id),
            )
            student_attendance = cursor.fetchall()
            attendance_data[student_id] = {
                class_id: status for class_id, status in student_attendance
            }

        # Create CSV
        output = StringIO()
        writer = csv.writer(output)

        # Write header: Student names followed by class dates
        header = ["Student Name"] + class_dates
        writer.writerow(header)

        # Write student attendance data
        for student_id, student_name in students:
            row = [student_name]
            for class_date in class_dates:
                # Find the class ID for this date
                class_entry = next(
                    (
                        cls
                        for cls in classes
                        if cls[1].strftime("%Y-%m-%d") == class_date
                    ),
                    None,
                )
                if class_entry:
                    class_id = class_entry[0]
                    row.append(attendance_data.get(student_id, {}).get(class_id, ""))
            writer.writerow(row)

        output.seek(0)

        # Get subject name for filename
        subject_name = next(
            (
                subject[1]
                for subject in subjects
                if subject[0] == int(selected_subject_id)
            ),
            "Unknown",
        )

        # Generate a response with the CSV file for download
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = (
            f"attachment; filename={subject_name}_attendance.csv"
        )
        response.headers["Content-type"] = "text/csv"

        cursor.close()
        conn.close()

        return response  # This sends the CSV file as a response

    # If it's a GET request, render the form
    cursor.close()
    conn.close()
    return render_template("export_subject_attendance.html", subjects=subjects)


@app.route("/edit_student", methods=["GET", "POST"])
def edit_student():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        # Handle POST request to update student information
        student_id = request.form.get("student_id")
        student_name = request.form.get("student_name")
        email = request.form.get("email")
        phone_number = request.form.get("phone_number")
        social_worker_email = request.form.get("social_worker_email")
        social_worker_phone = request.form.get("social_worker_phone")
        parent_email = request.form.get("parent_email")
        parent_phone = request.form.get("parent_phone")
        telegram_username = request.form.get("telegram_username")

        try:
            # Update the student info in the database
            cursor.execute(
                """
                UPDATE student SET 
                StudentName = %s, 
                Email = %s, 
                PhoneNumber = %s, 
                SocialWorkerEmail = %s, 
                SocialWorkerPhone = %s, 
                ParentEmail = %s, 
                ParentPhone = %s, 
                TelegramUsername = %s
                WHERE StudentID = %s
            """,
                (
                    student_name,
                    email,
                    phone_number,
                    social_worker_email,
                    social_worker_phone,
                    parent_email,
                    parent_phone,
                    telegram_username,
                    student_id,
                ),
            )
            conn.commit()
            flash("Student information updated successfully!", "success")
            return redirect(url_for("edit_student"))
        except Exception as e:
            flash(f"An error occurred: {str(e)}", "error")
            conn.rollback()

    # Handle GET request to fetch student info or display all students
    if "student_id" in request.args:
        student_id = request.args.get("student_id")
        cursor.execute("SELECT * FROM student WHERE StudentID = %s", (student_id,))
        student = cursor.fetchone()
    else:
        student = None

    # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    all_students = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "edit_student.html", student=student, all_students=all_students
    )


@app.route("/edit_marks", methods=["GET", "POST"])
def edit_marks():
    conn = get_db_connection()

    if not conn:
        flash("Could not connect to database!", "error")
        return redirect(url_for("error"))

    cursor = conn.cursor(dictionary=True)

    try:
        # Fetch data for dropdowns
        cursor.execute("SELECT StudentID, StudentName FROM student")
        students = cursor.fetchall()

        cursor.execute("SELECT SubjectID, SubjectName FROM subject")
        subjects = cursor.fetchall()

        if request.method == "POST":
            # Process marks update
            student_id = request.form.get("student_id")
            subject_id = request.form.get("subject_id")
            test_type = request.form.get("test_type")
            marks_obtained = request.form.get("marks_obtained")
            total_marks = request.form.get("total_marks")
            weightage = request.form.get("weightage")

            if all(
                [
                    student_id,
                    subject_id,
                    test_type,
                    marks_obtained,
                    total_marks,
                    weightage,
                ]
            ):
                # Check if record exists
                cursor.execute(
                    """
                    SELECT * FROM marks 
                    WHERE StudentID = %s AND SubjectID = %s AND TestType = %s
                    """,
                    (student_id, subject_id, test_type),
                )
                existing_record = cursor.fetchone()

                if existing_record:
                    # Update record
                    cursor.execute(
                        """
                        UPDATE marks 
                        SET MarksObtained = %s, TotalMarks = %s, Weightage = %s 
                        WHERE StudentID = %s AND SubjectID = %s AND TestType = %s
                        """,
                        (
                            marks_obtained,
                            total_marks,
                            weightage,
                            student_id,
                            subject_id,
                            test_type,
                        ),
                    )
                    conn.commit()
                    flash("Marks updated successfully!", "success")
                else:
                    flash(
                        "No existing record found for the given student and subject.",
                        "error",
                    )
            else:
                flash("All fields are required!", "error")

            return redirect(url_for("edit_marks"))

        # For GET request, populate the form with existing data if selected
        student_id = request.args.get("student_id")
        subject_id = request.args.get("subject_id")
        test_type = request.args.get("test_type")

        mark = None
        if student_id and subject_id and test_type:
            cursor.execute(
                "SELECT * FROM marks WHERE StudentID = %s AND SubjectID = %s AND TestType = %s",
                (student_id, subject_id, test_type),
            )
            mark = cursor.fetchone()

        # Fetch test types for the selected student and subject
        test_types = []
        if student_id and subject_id:
            cursor.execute(
                "SELECT DISTINCT TestType FROM marks WHERE StudentID = %s AND SubjectID = %s",
                (student_id, subject_id),
            )
            test_types = [row["TestType"] for row in cursor.fetchall()]

        return render_template(
            "edit_marks.html",
            students=students,
            subjects=subjects,
            mark=mark,
            test_types=test_types,
        )

    finally:
        cursor.close()
        conn.close()


@app.route("/get_test_details", methods=["GET"])
def get_test_details():
    student_id = request.args.get("student_id")
    subject_id = request.args.get("subject_id")

    if not student_id or not subject_id:
        return jsonify({"error": "Student or subject ID is missing."}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({"error": "Could not connect to database"}), 500

    with conn.cursor(dictionary=True) as cursor:
        cursor.execute(
            """
            SELECT TestType, MarksObtained, TotalMarks, Weightage 
            FROM marks 
            WHERE StudentID = %s AND SubjectID = %s
            """,
            (student_id, subject_id),
        )
        test_details = cursor.fetchall()

    if not test_details:
        return (
            jsonify(
                {"error": "No records found for the selected student and subject."}
            ),
            404,
        )

    return jsonify(test_details)


@app.route("/flash_message", methods=["POST"])
def flash_message():
    message = request.form.get("message")
    if message:
        flash(message, "error")  # Use the "error" category for this type of message
    return redirect(url_for("edit_marks"))




@app.route("/get_students_by_year", methods=["GET"])
def get_students_by_year():
    selected_year = request.args.get("year")

    if not selected_year:
        return jsonify({"error": "Year is required"}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Query to fetch students based on the selected intake year
        query = """
        SELECT DISTINCT s.StudentID, s.StudentName
        FROM student s
        JOIN attendance a ON s.StudentID = a.StudentID
        JOIN classes c ON c.ClassID = a.ClassID
        WHERE YEAR(c.ClassDate) = %s
        """

        cursor.execute(query, (selected_year,))
        data = cursor.fetchall()

        # Format the results as a list of dictionaries
        student_list = [
            {"StudentID": student[0], "StudentName": student[1]} for student in data
        ]

        return student_list

    except Exception as e:
        print(f"Error: {str(e)}")  # Log the error for debugging
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/set_term", methods=["GET", "POST"])
def set_term():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    if request.method == "POST":
        try:
            # Validate dates before updating
            for term_id in range(1, 4):
                start_date = datetime.strptime(request.form[f'start_date_{term_id}'], '%Y-%m-%d')
                end_date = datetime.strptime(request.form[f'end_date_{term_id}'], '%Y-%m-%d')
                
                # Check if start date is after end date
                if start_date > end_date:
                    flash(f"Term {term_id}: Start date cannot be after end date", "error")
                    return redirect(url_for('set_term'))

            # If all dates are valid, proceed with update
            for term_id in range(1, 4):
                start_date = request.form[f'start_date_{term_id}']
                end_date = request.form[f'end_date_{term_id}']
                
                cursor.execute("""
                    INSERT INTO term (id, start_date, end_date)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                        start_date = VALUES(start_date),
                        end_date = VALUES(end_date)
                """, (term_id, start_date, end_date))
            
            conn.commit()
            flash("Terms updated successfully!", "success")
            
        except Exception as e:
            conn.rollback()
            flash(f"Error updating terms: {str(e)}", "error")
            
        return redirect(url_for('set_term'))
    
    # Fetch existing terms
    cursor.execute("SELECT * FROM term ORDER BY id")
    terms = cursor.fetchall()
    
    # If no terms exist, create empty ones
    if not terms:
        terms = [
            {'id': i, 'start_date': '', 'end_date': ''} 
            for i in range(1, 4)
        ]
    
    cursor.close()
    conn.close()
    
    return render_template('term.html', terms=terms)

@app.route("/export_data", methods=["POST"])
def export_data():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create a timestamp for the export
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        export_dir = f'exports'
        os.makedirs(export_dir, exist_ok=True)
        
        # List of tables to export
        tables = [
            'attendance',
            'marks',
            'studentsubjects',
            'classes',
            'student',
            'user_channels',
        ]
        
        # Export each table to CSV
        for table in tables:
            cursor.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()
            
            # Get column names
            cursor.execute(f"SHOW COLUMNS FROM {table}")
            columns = [column[0] for column in cursor.fetchall()]
            
            # Write to CSV
            filepath = os.path.join(export_dir, f'{table}.csv')
            with open(filepath, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(columns)  # Write headers
                writer.writerows(rows)    # Write data
        
        # Create ZIP file
        zip_filepath = f'{export_dir}.zip'
        with ZipFile(zip_filepath, 'w') as zipf:
            for table in tables:
                csv_file = os.path.join(export_dir, f'{table}.csv')
                zipf.write(csv_file, f'{table}.csv')
                os.remove(csv_file)  # Remove individual CSV files
        
        os.rmdir(export_dir)  # Remove temporary directory
        
        # Send the ZIP file
        return send_file(
            zip_filepath,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f'attendance_marks_data_{timestamp}.zip'
        )
        
    except Exception as e:
        flash(f"Error exporting data: {str(e)}", "error")
        return redirect(url_for('delete_record'))
        
    finally:
        cursor.close()
        conn.close()

@app.route("/delete_record", methods=["GET", "POST"])
def delete_record():
    if request.method == "POST":
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # List of tables to truncate
            # Note: term, users table is not included in deletion
            tables = [
                'attendance',
                'marks',
                'studentsubjects',
                'classes',
                'student',
                'user_channels'
            ]
            
            # Disable foreign key checks temporarily
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            
            # Truncate all tables
            for table in tables:
                cursor.execute(f"TRUNCATE TABLE {table}")
            
            # Re-enable foreign key checks
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            
            conn.commit()
            flash("All records have been successfully deleted.", "success")
            
        except Exception as e:
            conn.rollback()
            flash(f"Error deleting records: {str(e)}", "error")
        finally:
            cursor.close()
            conn.close()
        
        return redirect(url_for('delete_record'))
        
    return render_template('delete_record.html')

import os
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = 'static'
ALLOWED_EXTENSIONS = {'jpg'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/upload_logo', methods=['POST'])
def upload_logo():
    if 'logo_file' not in request.files:
        flash('No file selected', 'warning')
        return redirect(url_for('generate_report'))
    
    file = request.files['logo_file']
    
    if file.filename == '':
        flash('No file selected', 'warning')
        return redirect(url_for('generate_report'))
    
    if file and allowed_file(file.filename):
        # Secure the filename and save it
        filename = 'starfish_text.jpg'  # Keep the same filename
        file_path = os.path.join(app.static_folder, filename)
        
        # If an old file exists, remove it
        if os.path.exists(file_path):
            os.remove(file_path)
            
        file.save(file_path)
        flash('Logo updated successfully', 'success')
        return redirect(url_for('generate_report'))
    
    flash('Invalid file type. Please use .jpg', 'warning')
    return redirect(url_for('generate_report'))

# session check for each route
@app.before_request
def check_user_logged_in():
    # List of routes that do not require login
    # Elements + js in static, accessible before login pages are listed
    public_routes = ["register", "login", "error", "static"]
    if (
        "user_id" not in session
        and "role" not in session
        and request.endpoint not in public_routes
    ):
        flash("Unauthorised access, log in and try again")
        # Redirect to login if user_id is not in session
        return redirect(url_for("login"))

    elif request.endpoint not in public_routes:
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "select role from users where user_id = %s", (session["user_id"],)
            )
            actual_role = cursor.fetchall()[0][0]

            if actual_role != session["role"]:
                flash("Unauthorised access, log in and try again")
                return redirect(url_for("login"))

        except mysql.connector.Error as err:
            flash(f"Error: {err}")
            conn.rollback()
            cursor.close()
            conn.close()
            return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
