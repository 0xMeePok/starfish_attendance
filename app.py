from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, make_response, render_template, session
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime, timedelta,time
import pandas as pd
import os
from dateutil import parser
import csv
import io
import logging
from io import StringIO
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from the .env file
load_dotenv()
logging.basicConfig(level=logging.DEBUG)
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallback_secret_key")
# Directory to save uploaded files
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

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
                cursor.execute("INSERT INTO Subject (SubjectName) VALUES (%s)", (new_subject,))
                conn.commit()
                subject_id = cursor.lastrowid

            # Insert the new class
            cursor.execute("INSERT INTO Classes (ClassDate, SubjectID) VALUES (%s, %s)", (class_date, subject_id))
            conn.commit()
            new_class_id = cursor.lastrowid

            # Get all students
            cursor.execute("SELECT StudentID FROM Student")
            students = cursor.fetchall()

            # Create attendance records for all students
            for student in students:
                cursor.execute("""
                    INSERT INTO Attendance (StudentID, ClassID, AttendanceStatus)
                    VALUES (%s, %s, 'Absent')
                """, (student[0], new_class_id))
            
            conn.commit()

            flash('New class created successfully and attendance records initialized for all students.', 'success')
        except mysql.connector.Error as err:
            conn.rollback()
            flash(f'Error creating class: {err}', 'error')
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('create_subject_class'))

    # Fetch existing subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM Subject ORDER BY SubjectName")
    subjects = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('create_subject_class.html', subjects=subjects)


"""
Enrolling of students to classes

CSV Format
StudentID, ClassID
"""
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

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Insert the new student into the database
            insert_query = """
            INSERT INTO Student (StudentName, Email, PhoneNumber, SocialWorkerEmail, SocialWorkerPhone, ParentEmail, ParentPhone)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (student_name, email, phone_number, social_worker_email, social_worker_phone, parent_email, parent_phone))
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
                if len(row) != 7:
                    flash(f'Invalid row in CSV: {row}. Expected 7 fields.', 'error')
                    continue

                student_name, email, phone_number, social_worker_email, social_worker_phone, parent_email, parent_phone = row

                # Insert the new student into the database
                insert_query = """
                INSERT INTO Student (StudentName, Email, PhoneNumber, SocialWorkerEmail, SocialWorkerPhone, ParentEmail, ParentPhone)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(insert_query, (student_name, email, phone_number, social_worker_email, social_worker_phone, parent_email, parent_phone))

            conn.commit()
            cursor.close()
            conn.close()

            flash('Students enrolled successfully from CSV!', 'success')
        except Exception as e:
            flash(f'Error processing CSV file: {str(e)}', 'error')
    else:
        flash('Invalid file type. Please upload a CSV file.', 'error')

    return redirect(url_for('enroll_student'))


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
            Student s
        JOIN 
            Attendance a ON s.StudentID = a.StudentID
        JOIN 
            Classes c ON a.ClassID = c.ClassID
        JOIN
            Subject sub ON c.SubjectID = sub.SubjectID
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
                # Convert timedelta to a formatted time string
                total_seconds = int(row['TimeAttended'].total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                row['TimeAttended'] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            elif row['TimeAttended'] is None:
                row['TimeAttended'] = 'N/A'

        cursor.close()
        conn.close()

        logging.debug("Rendering attendance.html template")
        return render_template('attendance.html', attendance_data=attendance_data)
    except Exception as e:
        logging.error(f"Error in overall_attendance route: {str(e)}")
        return f"An error occurred: {str(e)}", 500


@app.route("/attendance/<int:class_id>", methods=["GET"])
def attendance_for_specific_class(class_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Modify the query to filter by ClassID
    query = """
    SELECT 
    a.ClassId, 
    s.StudentID, 
    s.`Student Name`, 
    c.ClassName,
    c.Date, 
    a.TimeAttended,  -- Add this line to select TimeAttended
    a.Attended, 
    a.Remark, 
    a.Reason
    FROM 
        Attendance a
    JOIN 
        Student s ON a.StudentId = s.StudentID
    JOIN 
        Classes c ON a.ClassId = c.ClassId
    WHERE 
        a.ClassId = %s;

    """

    cursor.execute(query, (class_id,))
    attendance_data = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        "class_attendance.html", attendance_data=attendance_data, class_id=class_id
    )


@app.route('/update_attendance', methods=['POST'])
def update_attendance():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        for record in data:
            student_id = record['studentId']
            class_id = record['classId']
            status = record['status']
            reason = record.get('reason', '')

            # Update the attendance record
            update_query = """
            UPDATE Attendance
            SET AttendanceStatus = %s, Reason = %s
            WHERE StudentID = %s AND ClassID = %s
            """
            cursor.execute(update_query, (status, reason, student_id, class_id))

        conn.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        logging.error(f"Error updating attendance: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

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
        date_range_query = "SELECT MIN(ClassDate), MAX(ClassDate) FROM Classes"
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
            Classes c 
        LEFT JOIN 
            Attendance a 
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
    cursor.execute("SELECT StudentID, StudentName FROM Student")
    students = cursor.fetchall()

    if request.method == 'POST':
        subject = request.form['subject']
        test_type = request.form['test_type']
        student_id = request.form['student_id']
        marks_obtained = float(request.form['marks_obtained'])
        total_marks = float(request.form['total_marks'])
        weightage = float(request.form['weightage'])

        # Insert the marks into the database
        insert_query = """
        INSERT INTO Marks (StudentID, Subject, TestType, MarksObtained, TotalMarks, Weightage)
        VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(insert_query, (student_id, subject, test_type, marks_obtained, total_marks, weightage))
        conn.commit()

        cursor.close()
        conn.close()

        return redirect(url_for('create_marks'))

    cursor.close()
    conn.close()

    return render_template('create_marks.html', students=students)


@app.route("/export_class_attendance", methods=["GET", "POST"])
def export_class_attendance():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch all subjects for the dropdown
    cursor.execute("SELECT SubjectID, SubjectName FROM Subject")
    subjects = cursor.fetchall()

    if request.method == "POST":
        selected_subject_id = request.form.get("selected_subject")
        selected_class_date = request.form.get("selected_class_date")

        # Fetch attendance data for the selected subject and class date
        cursor.execute("""
            SELECT Student.StudentName, Attendance.AttendanceStatus
            FROM Attendance
            JOIN Student ON Attendance.StudentID = Student.StudentID
            JOIN Classes ON Attendance.ClassID = Classes.ClassID
            WHERE Classes.SubjectID = %s AND Classes.ClassDate = %s
        """, (selected_subject_id, selected_class_date))
        attendance_data = cursor.fetchall()
        # Fetch the subject name to include in the filename
        cursor.execute("SELECT SubjectName FROM Subject WHERE SubjectID = %s", (selected_subject_id,))
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
        cursor.execute("SELECT ClassDate FROM Classes WHERE SubjectID = %s", (subject_id,))
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
    cursor.execute("SELECT StudentID, StudentName FROM Student")
    students = cursor.fetchall()

    if request.method == "POST":
        selected_student_id = request.form.get("selected_student")

        # Fetch marks data for the selected student
        cursor.execute("""
            SELECT SubjectID, TestType, MarksObtained, TotalMarks, Weightage
            FROM Marks
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
        cursor.execute("SELECT StudentName FROM Student WHERE StudentID = %s", (selected_student_id,))
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
            cursor.execute("select password from USERS where username = %s", (request.form['username'],))
            hashed_pwd = cursor.fetchall()
            
            if hashed_pwd != []:
                authoriseBool = check_password_hash(hashed_pwd[0][0], request.form['password'])

                if authoriseBool:
                    cursor.execute("select user_id, role from USERS where username = %s", (request.form['username'],))
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
                cursor.execute("select role from USERS where user_id = %s", (session['user_id'],))
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
            cursor.execute("INSERT INTO USERS (username, password, role) VALUES (%s, %s, 0)", (request.form['username'], hashed_password))
            if cursor.rowcount == 0:
                flash("Username already exists, try another name")
                return redirect(url_for('register.html'))
            conn.commit()

            cursor.execute("select user_id, role from USERS where username = %s", (request.form['username'],))
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
                cursor.execute("select role from USERS where user_id = %s", (session['user_id'],))
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
    cursor.execute("SELECT StudentID, StudentName FROM Student")
    students = cursor.fetchall()

    if request.method == 'POST':
        # run pdf generating report function
        selected_year = request.form.get('selected_year')
        selected_student_id = request.form.get('selected_student')

        # querying all the data to popualate the fields
        retrieveDetails(selected_student_id, selected_year)

        data = {"Name": selected_student_id, "Ref_No": selected_year, }

        return render_template('report_template.html', data = data)

    else:
        return render_template('generate_report.html', students = students, years = years)
    
def retrieveDetails(student_id, year):
    conn = get_db_connection()
    cursor = conn.cursor()
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
    avg = {}

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
        if marks_data[n] != 0:
            if avg == {}: 
                avg['avg'] = marks_data[n]/len(marks_data)
            else:
                avg['avg'] += marks_data[n]/len(marks_data)
    marks_data['avg'] = round(avg['avg'],2)


    # cursor.execute("""

    # """, (student_id, year))
    


    final_data = [marks_data]
    cursor.close()
    conn.close()

    print(marks_data) # Return overall marks and the raw results if needed







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
            cursor.execute("select role from USERS where user_id = %s", (session['user_id'],))
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