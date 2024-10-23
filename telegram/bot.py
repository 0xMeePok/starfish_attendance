import telebot
from starfishdb import StarfishDB
import logging
import threading
from threading import Event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for testing
TEACHER_USERNAME = 'teacher_username'  # Replace with actual teacher username

class AttendanceBot:
    def __init__(self, token):
        self.bot = telebot.TeleBot(token, parse_mode=None)
        self.db = StarfishDB()
        self.stop_event = Event()
        self.thread = None
        self.setup_handlers()
        
    def setup_handlers(self):
        # General start command handler
        @self.bot.message_handler(commands=['start'])
        def start(message):
            logger.info(f"Received /start command from chat_id: {message.chat.id}")
            
            # Check if user has a username
            if not message.from_user.username:
                logger.warning("User has no username")
                self.bot.reply_to(message, "Please set a username in your Telegram settings first.")
                return

            username = f"@{message.from_user.username}"
            logger.info(f"Processing /start for username: {username}")

            try:
                # Check if user exists in database
                exists = self.db.user_exists(username)
                logger.info(f"User exists check for {username}: {exists}")

                if exists:
                    chat_id = message.chat.id
                    self.db.update_channel_id(username, chat_id)
                    
                    response = f"You are now verified as {username}.\nChannel ID: {chat_id}"
                    self.bot.reply_to(message, response)
                    
                    # Notify teacher if TEACHER_USERNAME is set and valid
                    try:
                        teacher_channel_id = self.db.get_channel_id(TEACHER_USERNAME)
                        if teacher_channel_id:
                            self.bot.send_message(teacher_channel_id, 
                                                f"Student verified as {username}.\nChannel ID: {chat_id}")
                    except Exception as e:
                        logger.error(f"Error notifying teacher: {e}")
                else:
                    self.bot.reply_to(message, 
                                    "You are not registered in the system. Please contact your administrator.")
            except Exception as e:
                logger.error(f"Error processing /start command: {e}")
                self.bot.reply_to(message, "An error occurred. Please try again later.")

        @self.bot.message_handler(commands=['help'])
        def send_help(message):
            help_text = """
            Available commands:
            /start - Start the bot and verify your account
            /help - Show this help message
            /status - Check your current attendance status
            """
            self.bot.reply_to(message, help_text)

        @self.bot.message_handler(commands=['status'])
        def check_status(message):
            if not message.from_user.username:
                self.bot.reply_to(message, "Please set a username in your Telegram settings first.")
                return

            username = f"@{message.from_user.username}"
            logger.info(f"Checking status for username: {username}")

            try:
                if not self.db.user_exists(username):
                    self.bot.reply_to(message, "You are not registered in the system.")
                    return

                details = self.db.get_student_details(username)
                if not details:
                    self.bot.reply_to(message, "No attendance records found.")
                    return

                status_text = f"""
                Latest attendance status:
                Date: {details[6]}
                Status: {details[3]}
                Time: {details[4] if details[4] else 'N/A'}
                Reason: {details[5] if details[5] else 'None provided'}
                """
                self.bot.reply_to(message, status_text)
            except Exception as e:
                logger.error(f"Error checking status: {e}")
                self.bot.reply_to(message, "An error occurred while checking your status.")

    def send_message(self, username, message_text):
        """Send a message to a specific user and handle their response"""
        try:
            channel_id = self.db.get_channel_id(username)
            if not channel_id:
                logger.error(f"No channel ID found for username: {username}")
                return False
                
            message = self.bot.send_message(channel_id, message_text)
            self.bot.register_next_step_handler(message, self._confirmation_handler)
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def _confirmation_handler(self, message):
        """Handle the confirmation step for late reasons"""
        chat_id = message.chat.id
        username = f"@{message.from_user.username}" if message.from_user.username else None
        text = message.text.strip()
        
        if not username:
            self.bot.send_message(chat_id, "Please set a username in your Telegram settings first.")
            return
        
        self.bot.send_message(chat_id, 
                            f"Confirm that this is your reason for being late (yes/no):\n<i><b>{text}</b></i>", 
                            parse_mode="html")
        
        # Register the next step handler with the original reason
        self.bot.register_next_step_handler(message, self._handle_reason, text)

    def _handle_reason(self, message, reason):
        """Handle the reason confirmation"""
        chat_id = message.chat.id
        username = f"@{message.from_user.username}" if message.from_user.username else None
        text = message.text.strip()
        
        if not username:
            self.bot.send_message(chat_id, "Please set a username in your Telegram settings first.")
            return
        
        if text.lower() == "yes":
            self.bot.send_message(chat_id, "Your reason has been recorded.")
            
            # Notify the teacher
            try:
                teacher_channel_id = self.db.get_channel_id(TEACHER_USERNAME)
                if teacher_channel_id:
                    self.bot.send_message(teacher_channel_id, f"{username} late due to:\n{reason}")
            except Exception as e:
                logger.error(f"Error notifying teacher about reason: {e}")
            
            # Update the reason in the database
            try:
                self.db.update_reason(username, reason)
            except Exception as e:
                logger.error(f"Error updating reason in database: {e}")
            return
            
        # If the user does not confirm the reason
        self.bot.send_message(chat_id, "Please re-enter your reason.")
        self.bot.register_next_step_handler(message, self._confirmation_handler)

    def run_bot(self):
        """Run the bot in a loop until stop_event is set"""
        while not self.stop_event.is_set():
            try:
                logger.info("Starting bot polling...")
                self.bot.polling(none_stop=True, timeout=60)
            except Exception as e:
                logger.error(f"Bot polling error: {e}")
                if not self.stop_event.is_set():
                    continue
            finally:
                self.bot.stop_polling()

    def run(self):
        """Start the bot in a separate thread"""
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self.run_bot)
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
            if self.thread.is_alive():
                logger.warning("Bot thread did not stop cleanly")
            else:
                logger.info("Bot stopped successfully")
            self.thread = None