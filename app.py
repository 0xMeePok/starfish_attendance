from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, make_response, render_template, session
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

TELEGRAM_DIR = Path(__file__).parent / 'telegram'
sys.path.append(str(TELEGRAM_DIR))

from telegram.bot_manager import BotManager

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

# Initialize bot manager
bot_manager = None
first_request = True

def init_bot():
    global bot_manager
    try:
        if bot_manager is None:
            logger.info("Initializing bot manager...")
            bot_manager = BotManager()
            
            # Schedule bot to start at 10:15 AM every Monday
            scheduler.add_job(
                bot_manager.start_bot,
                trigger=CronTrigger(
                    day_of_week='mon',
                    hour=10,
                    minute=15
                ),
                id='start_bot'
            )

            # Schedule bot to stop at 11:59 PM every Monday
            scheduler.add_job(
                bot_manager.stop_bot,
                trigger=CronTrigger(
                    day_of_week='mon',
                    hour=23,
                    minute=59
                ),
                id='stop_bot'
            )
            
            logger.info("Bot manager initialized and scheduled")
    except Exception as e:
        logger.error(f"Error initializing bot manager: {e}")

# Initialize bot after first request
@app.before_request
def before_request():
    global first_request
    if first_request:
        init_bot()
        first_request = False

# Clean up function
def cleanup():
    logger.info("Cleaning up...")
    if bot_manager:
        bot_manager.shutdown()
    if scheduler.running:
        scheduler.shutdown()

# Register cleanup function
atexit.register(cleanup)

# Add a route to check scheduler and bot status
@app.route('/status')
def check_status():
    return jsonify({
        'scheduler_running': scheduler.running,
        'bot_manager_initialized': bot_manager is not None,
        'bot_running': bot_manager.is_running if bot_manager else False
    })

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
    return render_template('error.html', error="The page you are looking for does not exist."), 404

# Custom handler for 500 Internal Server Error
@app.errorhandler(500)
def internal_server_error(e):
    return render_template('error.html', error="Internal Server Error."), 500


# Custom handler for other exceptions
@app.errorhandler(Exception)
def handle_exception(e):
    # Log the error details (only on the server side, not to the user)
    app.logger.error(f"Server error: {str(e)}")

    # Return a generic error message
    return render_template('error.html', error="Internal Server Error."), 500


def get_db_connection():
    """Establish a new database connection."""
    connection = mysql.connector.connect(**db_config)
    return connection


"""
Creation of Classes to map:


"""
@app.route('/create_subject_class', methods=['GET', 'POST'])
def create_subject_class():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    if request.method == 'POST':
        subject_id = request.form.get('subject_id')
        new_subject = request.form.get('new_subject')
        class_date = request.form.get('class_date')

        try:
            # If a new subject is provided, insert it
            if new_subject:
                cursor.execute("INSERT INTO subject (SubjectName) VALUES (%s)", (new_subject,))
                conn.commit()
                subject_id = cursor.lastrowid

            # Insert the new class
            cursor.execute("INSERT INTO classes (ClassDate, SubjectID) VALUES (%s, %s)", (class_date, subject_id))
            conn.commit()
            new_class_id = cursor.lastrowid

        except mysql.connector.Error as err:
            conn.rollback()
            flash(f'Error creating class: {err}', 'error')
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('create_subject_class'))

    # Fetch existing subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM subject ORDER BY SubjectName")
    subjects = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('create_subject_class.html', subjects=subjects)

def generate_channel_id():
    return 'channel_' + ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

@app.route('/enroll_student', methods=['GET', 'POST'])
def enroll_student():
    if request.method == 'POST':
        student_name = request.form['student_name']
        email = request.form['email']
        phone_number = request.form['phone_number']
        social_worker_email = request.form['social_worker_email']
        social_worker_phone = request.form['social_worker_phone']
        parent_email = request.form['parent_email']
        parent_phone = request.form['parent_phone']
        telegram_username = request.form['telegram_username']

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Generate a unique channel_id
            channel_id = generate_channel_id()
            while True:
                cursor.execute("SELECT COUNT(*) FROM student WHERE ChannelID = %s", (channel_id,))
                if cursor.fetchone()[0] == 0:
                    break
                channel_id = generate_channel_id()

            # Insert the new student into the database
            insert_query = """
            INSERT INTO student (StudentName, Email, PhoneNumber, SocialWorkerEmail, SocialWorkerPhone, ParentEmail, ParentPhone, TelegramUsername, ChannelID)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (student_name, email, phone_number, social_worker_email, social_worker_phone, parent_email, parent_phone, telegram_username, channel_id))
            conn.commit()

            flash('Student enrolled successfully!', 'success')
            return redirect(url_for('enroll_student'))
        except mysql.connector.Error as err:
            flash(f'Error enrolling student: {err}', 'error')
        finally:
            cursor.close()
            conn.close()

    return render_template('enroll_student.html')


@app.route('/upload_student_enrollment', methods=['POST'])
def upload_student_enrollment():
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('enroll_student'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('enroll_student'))
    
    if file and file.filename.endswith('.csv'):
        try:
            # Read the CSV file
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            csv_reader = csv.reader(stream)
            next(csv_reader)  # Skip header row if present

            conn = get_db_connection()
            cursor = conn.cursor()

            for row in csv_reader:
                if len(row) != 8:
                    flash(f'Invalid row in CSV: {row}. Expected 8 fields.', 'error')
                    continue

                student_name, email, phone_number, social_worker_email, social_worker_phone, parent_email, parent_phone, telegram_username = row

                # Generate a unique channel_id
                channel_id = generate_channel_id()
                while True:
                    cursor.execute("SELECT COUNT(*) FROM student WHERE ChannelID = %s", (channel_id,))
                    if cursor.fetchone()[0] == 0:
                        break
                    channel_id = generate_channel_id()

                # Insert the new student into the database
                insert_query = """
                INSERT INTO student (StudentName, Email, PhoneNumber, SocialWorkerEmail, SocialWorkerPhone, ParentEmail, ParentPhone, TelegramUsername, ChannelID)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(insert_query, (student_name, email, phone_number, social_worker_email, social_worker_phone, parent_email, parent_phone, telegram_username, channel_id))

            conn.commit()
            cursor.close()
            conn.close()

            flash('Students enrolled successfully from CSV!', 'success')
        except Exception as e:
            flash(f'Error processing CSV file: {str(e)}', 'error')
    else:
        flash('Invalid file type. Please upload a CSV file.', 'error')

    return redirect(url_for('enroll_student'))


@app.route('/enroll_classes', methods=['GET', 'POST'])
def enroll_classes():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    students = cursor.fetchall()

    # Fetch all subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM subject")
    subjects = cursor.fetchall()

    if request.method == 'POST':
        student_id = request.form['student_id']
        subject_id = request.form['subject_id']

        # Enroll the student in the subject (Insert into StudentSubjects)
        cursor.execute("""
            INSERT INTO studentsubjects (StudentID, SubjectID)
            VALUES (%s, %s)
        """, (student_id, subject_id))
        
        # Get all classes for the given SubjectID
        cursor.execute("""
            SELECT ClassID FROM classes WHERE SubjectID = %s
        """, (subject_id,))
        classes = cursor.fetchall()

        # Create attendance records for the student for each class
        for class_record in classes:
            cursor.execute("""
                INSERT INTO attendance (StudentID, ClassID, AttendanceStatus)
                VALUES (%s, %s, 'Absent')
            """, (student_id, class_record['ClassID']))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('enroll_classes'))

    cursor.close()
    conn.close()
    
    return render_template('enroll_classes.html', students=students, subjects=subjects)



# Attendance related functions
"""
Attendance related functions and routes below
Allows the marking of individual class
Allows the viewing of all attendance


"""


@app.route('/overall_attendance')
def overall_attendance():
    logging.debug("Entering overall_attendance route")
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch all student names
        cursor.execute("SELECT DISTINCT StudentName FROM student ORDER BY StudentName")
        all_students = [row['StudentName'] for row in cursor.fetchall()]

        # Fetch all subject names
        cursor.execute("SELECT DISTINCT SubjectName FROM subject ORDER BY SubjectName")
        all_subjects = [row['SubjectName'] for row in cursor.fetchall()]

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
            row['ClassDate'] = row['ClassDate'].strftime('%Y-%m-%d')
            if isinstance(row['TimeAttended'], timedelta):
                total_seconds = int(row['TimeAttended'].total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                row['TimeAttended'] = f"{hours:02d}:{minutes:02d}"
            elif row['TimeAttended'] is None:
                row['TimeAttended'] = ''

        cursor.close()
        conn.close()

        logging.debug("Rendering attendance.html template")
        return render_template('attendance.html', 
                               attendance_data=attendance_data, 
                               all_students=all_students,
                               all_subjects=all_subjects)
    except Exception as e:
        logging.error(f"Error in overall_attendance route: {str(e)}")
        return f"An error occurred: {str(e)}", 500
    
@app.route('/update_attendance', methods=['POST'])
def update_attendance():
    data = request.json
    logging.info(f"Received data: {data}")
    
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        for record in data:
            student_id = record['StudentID']
            class_id = record['ClassID']
            new_status = record['AttendanceStatus']
            time_attended = record.get('TimeAttended', '')  # Get the time from the request
            reason = record.get('Reason', '')

            # Fetch the current status of the student for the specific class
            cursor.execute("""
                SELECT AttendanceStatus, TimeAttended FROM attendance
                WHERE StudentID = %s AND ClassID = %s
            """, (student_id, class_id))
            current_record = cursor.fetchone()

            if not current_record:
                logging.error(f"No existing attendance record found for StudentID={student_id}, ClassID={class_id}")
                continue

            current_status, current_time_attended = current_record

            # Check if time_attended was provided in the request
            if not time_attended:
                # Only update TimeAttended if the status changes to 'Present' and was not 'Present' before
                if current_status != 'Present' and new_status == 'Present':
                    time_attended = datetime.now().strftime('%H:%M:%S')  # Set to current time
                    logging.info(f"TimeAttended updated to current time: {time_attended}")
                else:
                    time_attended = current_time_attended  # Retain the current time
            else:
                logging.info(f"TimeAttended manually updated to: {time_attended}")

            logging.info(f"Updating record: StudentID={student_id}, ClassID={class_id}, Status={new_status}, Time={time_attended}, Reason={reason}")

            # Update the attendance record
            update_query = """
            UPDATE attendance
            SET AttendanceStatus = %s, TimeAttended = %s, Reason = %s
            WHERE StudentID = %s AND ClassID = %s
            """
            cursor.execute(update_query, (new_status, time_attended, reason, student_id, class_id))
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


@app.route('/api/class-attendance', methods=["GET"])
def class_attendance():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')

        # Get the oldest and latest class records
        date_range_query = "SELECT MIN(ClassDate), MAX(ClassDate) FROM classes"
        cursor.execute(date_range_query)
        oldest_class_date, latest_class_date = cursor.fetchone()

        logging.debug(f"Oldest class date: {oldest_class_date}, Latest class date: {latest_class_date}")

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
            formatted_results.append({
                "dateString": row[0].strftime('%Y-%m-%d'),
                "PresentCount": row[1],
                "LateCount": row[2],
                "AbsentCount": row[3],
                "AbsentVRCount": row[4],
            })

        cursor.close()
        conn.close()

        response_data = {
            "data": formatted_results,
            "oldestClassDate": oldest_class_date.strftime('%Y-%m-%d'),
            "latestClassDate": latest_class_date.strftime('%Y-%m-%d')
        }
        logging.debug(f"Response data: {response_data}")

        return jsonify(response_data)

    except Exception as e:
        logging.error(f"Error fetching attendance data: {e}")
        return jsonify({"error": "An error occurred fetching data"}), 500
    
@app.route('/create_marks', methods=['GET', 'POST'])
def create_marks():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    students = cursor.fetchall()

    # Fetch all subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM subject")
    subjects = cursor.fetchall()

    if request.method == 'POST':
        subject = request.form['subject']
        test_type = request.form['test_type']
        student_id = request.form['student_id']
        marks_obtained = float(request.form['marks_obtained'])
        total_marks = float(request.form['total_marks'])
        weightage = float(request.form['weightage'])

        # Insert the marks into the database
        insert_query = """
        INSERT INTO marks (StudentID, Subject, TestType, MarksObtained, TotalMarks, Weightage)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (student_id, subject, test_type, marks_obtained, total_marks, weightage))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect(url_for('create_marks'))

    cursor.close()
    conn.close()

    # Pass both students and subjects to the template
    return render_template('create_marks.html', students=students, subjects=subjects)



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
        cursor.execute("""
            SELECT student.StudentName, attendance.AttendanceStatus
            FROM attendance
            JOIN student ON attendance.StudentID = student.StudentID
            JOIN classes ON attendance.ClassID = classes.ClassID
            WHERE classes.SubjectID = %s AND classes.ClassDate = %s
        """, (selected_subject_id, selected_class_date))
        attendance_data = cursor.fetchall()
        # Fetch the subject name to include in the filename
        cursor.execute("SELECT SubjectName FROM subject WHERE SubjectID = %s", (selected_subject_id,))
        subject_name = cursor.fetchone()[0]

        # Initialize categorized attendance dictionary for all statuses
        categorized_attendance = {
            "Present": [],
            "Late": [],
            "Absent": [],
            "Absent with VR": []
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
        formatted_date = datetime.strptime(selected_class_date, '%Y-%m-%d').strftime('%Y-%m-%d')
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
        cursor.execute("SELECT ClassDate FROM classes WHERE SubjectID = %s", (subject_id,))
        class_dates = cursor.fetchall()

        # Create a list of class dates to return as JSON
        result = {"classes": [{"ClassDate": class_date[0].strftime('%Y-%m-%d')} for class_date in class_dates]}
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

        # Fetch marks data for the selected student
        cursor.execute("""
            SELECT SubjectID, TestType, MarksObtained, TotalMarks, Weightage
            FROM marks
            WHERE StudentID = %s
        """, (selected_student_id,))
        marks_data = cursor.fetchall()

        # Create a CSV response
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(["SubjectID", "Test Type", "Marks Obtained", "Total Marks", "Weightage"])

        # Write marks data
        for row in marks_data:
            writer.writerow(row)

        output.seek(0)

        # Fetch student name for filename
        cursor.execute("SELECT StudentName FROM student WHERE StudentID = %s", (selected_student_id,))
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

#CREATE TABLE `users` (
#  `user_id` int NOT NULL AUTO_INCREMENT,
#  `username` varchar(50) NOT NULL,
#  `password` varchar(200) NOT NULL,
#  `role` int NOT NULL,
#  PRIMARY KEY (`user_id`)
#) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    authoriseBool = False

    # login logic
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("select password from users where username = %s", (request.form['username'],))
            hashed_pwd = cursor.fetchall()
            
            if hashed_pwd != []:
                authoriseBool = check_password_hash(hashed_pwd[0][0], request.form['password'])

                if authoriseBool:
                    cursor.execute("select user_id, role from users where username = %s", (request.form['username'],))
                    result = cursor.fetchone()
                    session['user_id'] = result[0]
                    session['role'] = result[1] 
                    return redirect(url_for('homepage'))
                else:
                    flash('incorrect username and password, try again')
                    return redirect(url_for('login'))
                
            else:
                flash('incorrect username and password, try again')
                return redirect(url_for('login'))

        except mysql.connector.Error as err:
            flash(f"Error: {err}")
            conn.rollback()
            return redirect(url_for('login'))
        finally:
            cursor.close()
            conn.close()
        
    else:
        # by default will run this when first navigated to
        conn = get_db_connection()
        cursor = conn.cursor()

        # check if already logged in, if yes redirect back to homepage
        if 'user_id' in session and 'role' in session:
            try:
                cursor.execute("select role from users where user_id = %s", (session['user_id'],))
                actual_role = cursor.fetchall()[0][0]

                if actual_role == session['role']:
                    return redirect(url_for('homepage')) 

            except mysql.connector.Error as err:
                flash(f"Error: {err}")
                conn.rollback()

            finally:
                cursor.close()
                conn.close()

        return render_template('login.html')    

@app.route('/homepage', methods=['GET', 'POST'])
def homepage():
    return render_template('homepage.html')

# to edit later
@app.route('/forgetpassword')
def forgetpassword():
    return render_template("forgetpassword.html")

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('role', None)
    flash("You have successfully logged out")
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            hashed_password = generate_password_hash(request.form['password'])
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 0)", (request.form['username'], hashed_password))
            if cursor.rowcount == 0:
                flash("Username already exists, try another name")
                return redirect(url_for('register.html'))
            conn.commit()

            cursor.execute("select user_id, role from users where username = %s", (request.form['username'],))
            result = cursor.fetchone()
            session['user_id'] = result[0]
            session['role'] = result[1]  # Store the role
            cursor.close()
            conn.close()

            return redirect(url_for('homepage'))

        except mysql.connector.Error as err:
            flash(f"Error: {err}")
            conn.rollback()
            cursor.close()
            conn.close()
            return render_template('register.html')
    else:
        conn = get_db_connection()
        cursor = conn.cursor()

        # check if already logged in, if yes redirect back to homepage
        if 'user_id' in session and 'role' in session:
            try:
                cursor.execute("select role from users where user_id = %s", (session['user_id'],))
                actual_role = cursor.fetchall()[0][0]

                if actual_role == session['role']:
                    return redirect(url_for('homepage')) 
            except:
                flash(f"Error: {err}")
                conn.rollback()
                cursor.close()
                conn.close()
                return render_template('register.html')

        return render_template('register.html')


@app.route('/error', methods=['GET', 'POST'])
def errorPage(err):
    return render_template('error.html', error=err)

@app.route('/generate_report', methods=['GET', 'POST'])
def generate_report():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT ClassDate FROM classes")
    classDates = cursor.fetchall()
    years = [row[0].year for row in classDates]
    max_year = min(years)
    min_year = min(years)
    years = []

    list_of_years = range(min_year, max_year+1)
    
    for n in list_of_years:
        years.append(n)

     # Fetch all students for the dropdown
    cursor.execute("SELECT StudentID, StudentName FROM student")
    students = cursor.fetchall()

    if request.method == 'POST':
        # run pdf generating report function
        selected_report = request.form.get('selected_report')
        selected_year = request.form.get('selected_year')
        selected_student_id = request.form.get('selected_student')

        # querying all the data to popualate the fields
        name, marks_data, attendanceByStatus, year = retrieveDetails(selected_student_id, selected_year, selected_report)
        
        data = {"name": name, "marks": marks_data, "attendanceByStatus" : attendanceByStatus, "year": year}

        if selected_report == "0":
            return render_template('report_overall_template.html', data = data)
        else:
            return render_template('report_progress_template.html', data = data)

    else:
        return render_template('generate_report.html', students = students, years = years)

def retrieveDetails(student_id, year, selected_report):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT StudentName
            FROM student
            WHERE StudentID = %s;
        """, (student_id,))

        name = cursor.fetchall()
        
    except Exception as e:
        print(f"An error occurred: {e}")

    # Execute the SQL query
    try:
        cursor.execute("""
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
        """, (student_id, year))
        # Fetch all results
        results = cursor.fetchall()

    except Exception as e:
        print(f"An error occurred: {e}")
    
    # Initialize variables to calculate overall marks
    marks_data = {}

    for row in results:
        student_id, subject, marks_obtained, total_marks, weightage = row
        
        if subject not in marks_data:
            if marks_obtained == 0:
                marks_data[subject] = 0
            else:
                marks_data[subject] = marks_obtained / total_marks * weightage
        else:
            if marks_obtained == 0:
                marks_data[subject] += 0
            else:
                marks_data[subject] += marks_obtained / total_marks * weightage


    for n in marks_data:
            marks_data[n] = [marks_data[n] , get_grade(marks_data[n])]

    cursor.execute("""
        SELECT a.AttendanceStatus, COUNT(*) AS numOfAttendance 
        FROM attendance a
        JOIN classes c ON a.ClassID = c.ClassID 
        WHERE a.StudentID = %s AND YEAR(c.ClassDate) = %s 
        GROUP BY a.AttendanceStatus
    """, (student_id, year))

    attendanceByStatus = cursor.fetchall()
    attendanceByStatus = dict(attendanceByStatus)

    totalSum = sum(attendanceByStatus.values())

    if 'Absent with VR' not in attendanceByStatus:
        attendanceByStatus['Absent with VR'] = 0

    if 'Late' not in attendanceByStatus:
        attendanceByStatus['Late'] = 0    

    if 'Present' not in attendanceByStatus:
        attendanceByStatus['Present'] = 0       

    attendanceByStatus['total'] = totalSum

    cursor.close()
    conn.close()
    print(name, marks_data, attendanceByStatus, year)

    return name, marks_data, attendanceByStatus, year

def get_grade(score):
    if 75 <= score <= 100:
        return 'A'
    elif 70 <= score <= 74:
        return 'B'
    elif 60 <= score <= 73:
        return 'C'
    elif 50 <= score <= 59:
        return 'D'
    elif 0 <= score <= 49:
        return 'E'
    
@app.route('/get_students_by_year', methods=['GET'])
def get_students_by_year():
    selected_year = request.args.get('year')

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
        student_list = [{"StudentID": student[0], "StudentName": student[1]} for student in data]

        return student_list

    except Exception as e:
        print(f"Error: {str(e)}")  # Log the error for debugging
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# session check for each route
@app.before_request
def check_user_logged_in():
    # List of routes that do not require login
    public_routes = ['register', 'login', 'error', 'static']  # Elements + js in static, accessible before login pages are listed 
    if 'user_id' not in session and 'role' not in session and request.endpoint not in public_routes:
        flash("Unauthorised access, log in and try again")
        return redirect(url_for('login'))  # Redirect to login if user_id is not in session
    
    elif request.endpoint not in public_routes:
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("select role from users where user_id = %s", (session['user_id'],))
            actual_role = cursor.fetchall()[0][0]

            if actual_role != session['role']:
                flash("Unauthorised access, log in and try again")
                return redirect(url_for('login')) 

        except mysql.connector.Error as err:
            flash(f"Error: {err}")
            conn.rollback()
            cursor.close()
            conn.close()
            return redirect(url_for('login'))



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)