import telebot
from starfishdb import StarfishDB
import logging
from threading import Thread, Event
from datetime import datetime, time, date
import time as time_module

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

ABSENCE_KEYWORDS = [
    'mc', 'sick', 'headache', 'fever', 'unwell', 'hospital', 
    'doctor', 'medical', 'appointment', 'emergency', 'family',
    'ill', 'not feeling well', 'cannot make it', "can't make it"
]

class AttendanceBot:
    def __init__(self, token, teacher_username):
        self.bot = telebot.TeleBot(token, parse_mode="html")
        self.db = StarfishDB()
        self.stop_event = Event()
        self.thread = None
        self.teacher_username = teacher_username
        self.setup_handlers()
        logger.info("AttendanceBot initialized")

    def setup_handlers(self):
        @self.bot.message_handler(func=lambda message: True)
        def handle_messages(message):
            try:
                chat_id, username = message.chat.id, message.chat.username
                print(chat_id)

                self.db.update_channel_id(username, chat_id)
                username = f"@{message.from_user.username}" if message.from_user.username else None
                text = message.text.strip().lower()

                if not username:
                    self.bot.reply_to(message, "Please set a username in your Telegram settings.")
                    return

                logger.info(f"Received message from {username}: {text}")

                # Check if we're expecting a response from this student
                if self.db.is_awaiting_response(username):
                    self.handle_absence_reason(username, text)

            except Exception as e:
                logger.error(f"Error handling message: {e}")

    def handle_absence_reason(self, username, text):
        """Process the student's response for absence"""
        try:
            # Check for absence keywords in the message
            reason_given = any(keyword in text.lower() for keyword in ABSENCE_KEYWORDS)
            
            if reason_given:
                # Update the database with the reason
                self.db.update_attendance_with_reason(username, text, 'Absent with VR')
                
                # Send confirmation to student
                student_chat_id = self.db.get_channel_id(username)
                if student_chat_id:
                    self.bot.send_message(
                        student_chat_id,
                        "Thank you for informing. Your absence has been recorded."
                    )

                # Notify teacher
                teacher_chat_id = self.db.get_channel_id(self.teacher_username)
                if teacher_chat_id:
                    student_name = self.db.get_student_name(username)
                    self.bot.send_message(
                        teacher_chat_id,
                        f"🔴 Absence Notice:\nStudent: {student_name} ({username})\nReason: {text}"
                    )
            else:
                # If no valid reason is detected
                student_chat_id = self.db.get_channel_id(username)
                if student_chat_id:
                    self.bot.send_message(
                        student_chat_id,
                        "I didn't quite understand. Are you unable to attend class today? Please provide a reason."
                    )

        except Exception as e:
            logger.error(f"Error handling absence reason: {e}")

    def check_attendance(self):
        """Check for absent students and send messages"""
        try:
            logger.info("Checking attendance...")
            today = date.today()
            absent_students = self.db.get_absent_students(today)
            print(absent_students)
            for student in absent_students:
                chat_id = self.db.get_channel_id(student['username'])
                if chat_id:
                    self.bot.send_message(
                        chat_id,
                        "Hey! Are you coming to class today? Let me know."
                    )
                    # Mark student as awaiting response
                    self.db.set_awaiting_response(student['username'])
                    logger.info(f"Sent attendance check message to {student['username']}")

        except Exception as e:
            logger.error(f"Error in check_attendance: {e}")

    def run_bot(self):
        """Run the bot in a loop until stop_event is set"""
        while not self.stop_event.is_set():
            try:
                logger.info("Starting bot polling...")
                self.bot.polling(none_stop=True, timeout=60)
            except Exception as e:
                logger.error(f"Error in bot polling: {e}")
                if not self.stop_event.is_set():
                    time_module.sleep(5)  # Wait before retrying
                    continue
            finally:
                self.bot.stop_polling()

    def run(self):
        """Start the bot in a separate thread"""
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = Thread(target=self.run_bot)
            self.thread.daemon = True
            self.thread.start()
            logger.info("Bot thread started")

    def stop(self):
        """Stop the bot and its thread"""
        if self.thread and self.thread.is_alive():
            logger.info("Stopping bot...")
            self.stop_event.set()
            self.bot.stop_polling()
            self.thread.join(timeout=5)
            logger.info("Bot stopped")