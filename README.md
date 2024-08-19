# Starfish Attendance System
Simple Starfish Attendance System which allows tutors to mark attendance of all classes. LogIn to use app. It has an integration of a dedicated telegram bot to prompt latecomers or allow them to give a valid reason. Interface also has the ability to automatically generate report cards of a student's performance/attendance.

Non-Tech users should already be given the script to run to automatically start up everything

# How to Run (For Dev Use)
```bash
# first run
git clone https://github.com/0xMeePok/starfish_attendance
cd starfish_attendance
python3 -m venv .venv
source activate
pip3 install -r requirements.txt
sudo mysql.server start
flask --app backend.py run
```

```bash
# subsequent runs
cd starfish_attendance
sudo mysql.server start
flask --app backend.py run
```


# Stack

Frontend:
HTML/ JS 
CSS 

Backend:
Python Flask
MySQL
Telegram Bot API

Infras:
Zero-Tier
