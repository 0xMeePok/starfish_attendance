from flask import Flask, render_template, jsonify, request
import mysql.connector
from dotenv import load_dotenv
import os

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)

# Database connection details using environment variables
db_config = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
}


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
    c.Date,
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
    c.Date,
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

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    update_query = """
    UPDATE Attendance
    SET Attended = %s
    WHERE ClassId = %s AND StudentId = %s
    """
    cursor.execute(update_query, (attended, class_id, student_id))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"status": "success"})


@app.route("/")
def home():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)
