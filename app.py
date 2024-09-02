from flask import Flask, render_template, jsonify, request
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
import os
from dateutil import parser
import sys

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

ClassID, ClassName, Date and Time of class
"""


@app.route("/create_class", methods=["GET", "POST"])
def create_class():
    if request.method == "POST":
        # Get form data (exclude ClassId)
        class_name = request.form["class_name"]
        class_date = request.form["class_date"]
        class_time = request.form["class_time"]

        # Combine date and time into a single datetime object
        class_datetime_str = f"{class_date} {class_time}"
        class_datetime = datetime.strptime(class_datetime_str, "%Y-%m-%d %H:%M")

        # Insert the new class into the database (ClassId will be auto-incremented)
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        insert_query = """
        INSERT INTO Classes (ClassName, Date)
        VALUES (%s, %s)
        """
        cursor.execute(insert_query, (class_name, class_datetime))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({"status": "success", "message": "Class created successfully!"})

    return render_template("create_class.html")


@app.route("/upload_classes", methods=["GET", "POST"])
def upload_classes():
    if request.method == "POST":
        # Check if a file is uploaded
        if "file" not in request.files:
            return jsonify({"status": "error", "message": "No file part"})

        file = request.files["file"]

        if file.filename == "":
            return jsonify({"status": "error", "message": "No selected file"})

        if file and (file.filename.endswith(".csv") or file.filename.endswith(".xlsx")):
            # Save the uploaded file
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
            file.save(filepath)

            try:
                # Read the file into a DataFrame
                if file.filename.endswith(".csv"):
                    df = pd.read_csv(filepath)
                elif file.filename.endswith(".xlsx"):
                    df = pd.read_excel(filepath)

                # Validate required columns
                if not {"ClassName", "Date"}.issubset(df.columns):
                    return jsonify(
                        {
                            "status": "error",
                            "message": "File does not contain the required headers: 'ClassName', 'Date'",
                        }
                    )

                # Process each row
                conn = mysql.connector.connect(**db_config)
                cursor = conn.cursor()

                for index, row in df.iterrows():
                    class_name = row["ClassName"]
                    class_datetime = parser.parse(
                        str(row["Date"])
                    )  # Use parser to handle different date-time formats

                    insert_query = """
                    INSERT INTO Classes (ClassName, Date)
                    VALUES (%s, %s)
                    """
                    cursor.execute(insert_query, (class_name, class_datetime))

                conn.commit()
                cursor.close()
                conn.close()

                # Delete the file after processing
                os.remove(filepath)

                return jsonify(
                    {
                        "status": "success",
                        "message": "Classes created successfully from file!",
                    }
                )

            except Exception as e:
                return jsonify({"status": "error", "message": str(e)})

        else:
            return jsonify(
                {
                    "status": "error",
                    "message": "Unsupported file format. Please upload a .csv or .xlsx file.",
                }
            )

    return render_template("upload_classes.html")


"""
Enrolling of students to classes

CSV Format
StudentID, ClassID
"""


@app.route("/enroll_student", methods=["GET", "POST"])
def enroll_student():
    if request.method == "POST":
        student_id = request.form["student_id"]
        class_id = request.form["class_id"]

        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        # Check if the student is already enrolled in the class
        check_query = """
        SELECT COUNT(*) FROM Attendance WHERE StudentID = %s AND ClassID = %s
        """
        cursor.execute(check_query, (student_id, class_id))
        count = cursor.fetchone()[0]

        if count > 0:
            return jsonify(
                {
                    "status": "error",
                    "message": "Student is already enrolled in this class.",
                }
            )

        # Proceed with the enrollment
        insert_query = """
        INSERT INTO Attendance (StudentID, ClassID, Attended)
        VALUES (%s, %s, 0)
        """
        cursor.execute(insert_query, (student_id, class_id))
        conn.commit()

        cursor.close()
        conn.close()

        return jsonify(
            {"status": "success", "message": "Student enrolled successfully!"}
        )

    return render_template("enroll_student.html")


@app.route("/upload_student_enrollment", methods=["POST"])
def upload_student_enrollment():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file part"})

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"status": "error", "message": "No selected file"})

    if file and (file.filename.endswith(".csv") or file.filename.endswith(".xlsx")):
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
        file.save(filepath)

        try:
            if file.filename.endswith(".csv"):
                df = pd.read_csv(filepath)
            elif file.filename.endswith(".xlsx"):
                df = pd.read_excel(filepath)

            if not {"StudentID", "ClassID"}.issubset(df.columns):
                return jsonify(
                    {
                        "status": "error",
                        "message": "File does not contain the required headers: 'StudentID', 'ClassID'",
                    }
                )

            conn = mysql.connector.connect(**db_config)
            cursor = conn.cursor()

            for index, row in df.iterrows():
                student_id = int(row["StudentID"])  # Convert numpy.int64 to Python int
                class_id = int(row["ClassID"])  # Convert numpy.int64 to Python int

                # Check if the student is already enrolled in the class
                check_query = """
                SELECT COUNT(*) FROM Attendance WHERE StudentID = %s AND ClassID = %s
                """
                cursor.execute(check_query, (student_id, class_id))
                count = cursor.fetchone()[0]

                if count == 0:
                    insert_query = """
                    INSERT INTO Attendance (StudentID, ClassID, Attended)
                    VALUES (%s, %s, 0)
                    """
                    cursor.execute(insert_query, (student_id, class_id))

            conn.commit()
            cursor.close()
            conn.close()

            os.remove(filepath)

            return jsonify(
                {
                    "status": "success",
                    "message": "Students enrolled successfully from file!",
                }
            )

        except Exception as e:
            return jsonify({"status": "error", "message": str(e)})

    return jsonify(
        {
            "status": "error",
            "message": "Unsupported file format. Please upload a .csv or .xlsx file.",
        }
    )


# Attendance related functions
"""
Attendance related functions and routes below
Allows the marking of individual class
Allows the viewing of all attendance


"""


@app.route("/overall_attendance")
def attendance():
    # Establish a connection to the database
    conn = mysql.connector.connect(**db_config)
    if conn.is_connected():
        pass
    else:
        print("Failed to connect to the database")
    cursor = conn.cursor()

    # Query to select attendance data
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


    """

    cursor.execute(query)
    attendance_data = cursor.fetchall()

    # Close the connection
    cursor.close()
    conn.close()

    return render_template("attendance.html", attendance_data=attendance_data)


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


@app.route("/update_attendance", methods=["POST"])
def update_attendance():
    data = request.json
    class_id = data["class_id"]
    student_id = data["student_id"]
    attended = data["attended"]
    current_time = datetime.now()  # Get the current datetime

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    update_query = """
    UPDATE Attendance
    SET Attended = %s, TimeAttended = %s
    WHERE ClassId = %s AND StudentId = %s
    """
    cursor.execute(update_query, (attended, current_time, class_id, student_id))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status": "success"})


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

    # Corrected SQL query
    query = """
      SELECT 
        DATE(c.Date) as DateString,
        SUM(CASE WHEN c.classname = 'English' THEN a.Attended ELSE 0 END) AS EnglishAttendance,
        SUM(CASE WHEN c.classname = 'Math' THEN a.Attended ELSE 0 END) AS MathAttendance,
        SUM(CASE WHEN c.classname = 'Science' THEN a.Attended ELSE 0 END) AS ScienceAttendance
      FROM 
        Classes c 
      LEFT JOIN 
        Attendance a 
      ON 
        c.ClassId = a.ClassID 
      GROUP BY 
        DATE(c.Date) 
      ORDER BY 
        DateString;
    """

    cursor.execute(query)
    results = cursor.fetchall()

    # Convert results to desired format (list of dictionaries)
    formatted_results = []
    for row in results:
      formatted_results.append({
        "dateString": row[0],
        "EnglishAttendance": row[1],
        "MathAttendance": row[2],
        "ScienceAttendance": row[3],
      })

    cursor.close()
    conn.close()

    return jsonify(formatted_results)

  except Exception as e:
    print(f"Error fetching attendance data: {e}")
    # Consider returning a proper error response with status code
    return jsonify({"error": "An error occurred fetching data"}), 500


@app.route("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
