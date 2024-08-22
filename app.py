from flask import Flask, render_template, jsonify, request
import mysql.connector
from dotenv import load_dotenv
import os

# Load environment variables from the .env file
load_dotenv()

app = Flask(__name__)

# Database connection details using environment variables
db_config = {
    'host': os.getenv('DB_HOST'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'database': os.getenv('DB_NAME')
}


@app.route('/attendance')
def attendance():
    # Establish a connection to the database
    conn = mysql.connector.connect(**db_config)
    if conn.is_connected():
        print("Connected to the database")
    else:
        print("Failed to connect to the database")
    cursor = conn.cursor()

    # Query to select attendance data
    query = """
    SELECT ClassId, StudentId, Date, Attended, Remarks, Reason
    FROM Attendance_Table
    """

    cursor.execute(query)
    attendance_data = cursor.fetchall()
    print(attendance_data)

    # Close the connection
    cursor.close()
    conn.close()

    return render_template('attendance.html', attendance_data=attendance_data)


@app.route('/update_attendance', methods=['POST'])
def update_attendance():
    data = request.json
    class_id = data['class_id']
    student_id = data['student_id']
    attended = data['attended']

    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor()

    update_query = """
    UPDATE Attendance_Table
    SET Attended = %s
    WHERE ClassId = %s AND StudentId = %s
    """

    # Execute the prepared statement with the provided values
    cursor.execute(update_query, (attended, class_id, student_id))
    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({'status': 'success'})


if __name__ == '__main__':
    app.run(debug=True)
