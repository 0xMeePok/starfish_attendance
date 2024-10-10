from flask import Flask, render_template, jsonify, request, redirect, url_for, flash, make_response
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pandas as pd
import os
from dateutil import parser
import csv
import io
import logging
from io import StringIO

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)
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
    return render_template("index.html"), 404


# Custom handler for 500 Internal Server Error
@app.errorhandler(500)
def internal_server_error(e):
    return render_template("index.html"), 500


# Custom handler for other exceptions
@app.errorhandler(Exception)
def handle_exception(e):
    # Log the error details (only on the server side, not to the user)
    app.logger.error(f"Server error: {str(e)}")

    # Return a generic error message
    return render_template("index.html"), 500


@app.route("/")
def index():
    return render_template("index.html")


"""
Creation of Classes to map:


"""
@app.route("/create_subject_class", methods=["GET", "POST"])
def create_subject_class():
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    # Fetch all existing subjects
    cursor.execute("SELECT SubjectID, SubjectName FROM Subject")
    subjects = cursor.fetchall()

    cursor.close()
    conn.close()

    if request.method == "POST":
        # Check for both the selected subject and the manually entered one
        selected_subject_id = request.form.get("selected_subject")  # Existing subject
        subject_name = request.form.get("subject_name")  # New subject entered

        # Get form data for the class date
        class_date = request.form["class_date"]

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # If the user enters a new subject, check if it already exists
        if not selected_subject_id and subject_name:
            check_subject_query = """
            SELECT SubjectID FROM Subject WHERE SubjectName = %s
            """
            cursor.execute(check_subject_query, (subject_name,))
            existing_subject = cursor.fetchone()

            if existing_subject:
                # If subject exists, use its ID
                subject_id = existing_subject[0]
            else:
                # If the subject does not exist, insert it
                insert_subject_query = """
                INSERT INTO Subject (SubjectName)
                VALUES (%s)
                """
                cursor.execute(insert_subject_query, (subject_name,))
                subject_id = cursor.lastrowid  # Get the newly inserted SubjectID
        else:
            # Use the selected subject ID if it was chosen
            subject_id = selected_subject_id

        # Insert class with ClassDate and SubjectID
        insert_class_query = """
        INSERT INTO Classes (ClassDate, SubjectID)
        VALUES (%s, %s)
        """
        cursor.execute(insert_class_query, (class_date, subject_id))

        conn.commit()
        cursor.close()
        conn.close()

        return jsonify({"status": "success", "message": "Subject and class created successfully!"})

    return render_template("create_subject_class.html", subjects=subjects)




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

        conn = mysql.connector.connect(**db_config)
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

            conn = mysql.connector.connect(**db_config)
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
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)

    query = """
    SELECT 
        s.StudentID,
        s.StudentName,
        c.ClassID,
        c.ClassDate,
        a.AttendanceStatus,
        a.TimeAttended,
        a.Reason
    FROM 
        Student s
    JOIN 
        Attendance a ON s.StudentID = a.StudentID
    JOIN 
        Classes c ON a.ClassID = c.ClassID
    ORDER BY 
        c.ClassDate DESC, s.StudentName
    """

    cursor.execute(query)
    attendance_data = cursor.fetchall()

    # Format the datetime objects
    for row in attendance_data:
        row['ClassDate'] = row['ClassDate'].strftime('%Y-%m-%d')
        if isinstance(row['TimeAttended'], timedelta):
            # Convert timedelta to a formatted time string
            seconds = row['TimeAttended'].total_seconds()
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            row['TimeAttended'] = f"{hours:02d}:{minutes:02d}"
        elif row['TimeAttended'] is None:
            row['TimeAttended'] = 'N/A'

    cursor.close()
    conn.close()

    return render_template('attendance.html', attendance_data=attendance_data)


@app.route("/attendance/<int:class_id>", methods=["GET"])
def attendance_for_specific_class(class_id):
    conn = mysql.connector.connect(**db_config)
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
    student_id = data['student_id']
    class_id = data['class_id']
    status = data['status']
    reason = data.get('reason', '')

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    try:
        # Get the class date
        cursor.execute("SELECT ClassDate FROM Classes WHERE ClassID = %s", (class_id,))
        class_date = cursor.fetchone()[0]

        # Determine if it's late based on the current time (if status is 'Present')
        current_time = datetime.now().time()
        if status == 'Present' and current_time > datetime.time(10, 15):
            status = 'Late'

        # Update the attendance record
        update_query = """
        UPDATE Attendance
        SET AttendanceStatus = %s, TimeAttended = %s, Reason = %s
        WHERE StudentID = %s AND ClassID = %s
        """
        cursor.execute(update_query, (status, current_time, reason, student_id, class_id))
        conn.commit()

        return jsonify({"status": "success"})
    except Exception as e:
        print(f"Error updating attendance: {e}")
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

    conn = mysql.connector.connect(**db_config)
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
    conn = mysql.connector.connect(**db_config)
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
        conn = mysql.connector.connect(**db_config)
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
    conn = mysql.connector.connect(**db_config)
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
    conn = mysql.connector.connect(**db_config)
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

    conn = mysql.connector.connect(**db_config)
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


@app.route("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
