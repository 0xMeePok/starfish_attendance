import requests
    
username = "student_username"  # Replace with actual student username
message = "Reminder: Your class started 5 minutes ago.\nPlease state your reason for being late.",

requests.post('http://localhost:5001/send_message', json={'username': username, 'message': message})
            
