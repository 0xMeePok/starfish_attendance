import telebot
from starfishdb import StarfishDB
import logging
from threading import Event, Thread
from datetime import datetime, time, date
import time as time_module

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class AttendanceBot:
    def __init__(self, token):
        logger.info("Initializing AttendanceBot...")
        self.bot = telebot.TeleBot(token, parse_mode="html")
        self.db = StarfishDB()
        self.stop_event = Event()
        self.thread = None
        logger.info("Setting up message handlers...")
        self.setup_handlers()
        logger.info("AttendanceBot initialized successfully")

    def setup_handlers(self):
        try:
            @self.bot.message_handler(func=lambda message: True)
            def handle_all_messages(message):
                logger.info(f"Received message from {message.from_user.username}")
                chat_id = message.chat.id
                username = f"@{message.from_user.username}" if message.from_user.username else None
                text = message.text.strip()

                if not username:
                    self.bot.reply_to(message, "Please set a username in your Telegram settings.")
                    return

                logger.info(f"Processing message from {username}: {text}")
                # Rest of your message handling logic...

            logger.info("Message handlers set up successfully")
        except Exception as e:
            logger.error(f"Error setting up handlers: {e}", exc_info=True)
            raise

    def run_bot(self):
        """Run the bot in a loop until stop_event is set"""
        logger.info("Starting bot polling...")
        while not self.stop_event.is_set():
            try:
                logger.info("Beginning bot polling...")
                self.bot.polling(none_stop=True, timeout=60)
            except Exception as e:
                logger.error(f"Error in bot polling: {e}", exc_info=True)
                if not self.stop_event.is_set():
                    continue
                break
            finally:
                logger.info("Stopping bot polling...")
                self.bot.stop_polling()

    def run(self):
        """Start the bot in a separate thread"""
        logger.info("Attempting to start bot thread...")
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            logger.info("Creating new bot thread...")
            self.thread = Thread(target=self.run_bot)
            self.thread.daemon = True
            logger.info("Starting bot thread...")
            self.thread.start()
            logger.info("Bot thread started successfully")
        else:
            logger.warning("Bot thread already running")

    def stop(self):
        """Stop the bot and its thread"""
        logger.info("Attempting to stop bot...")
        if self.thread and self.thread.is_alive():
            logger.info("Setting stop event...")
            self.stop_event.set()
            logger.info("Stopping bot polling...")
            self.bot.stop_polling()
            logger.info("Waiting for thread to join...")
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                logger.warning("Bot thread did not stop cleanly")
            else:
                logger.info("Bot thread stopped successfully")
            self.thread = None
        else:
            logger.info("Bot was not running")

    def handle_late_reason(self, chat_id, username, reason):
        """Handle the submitted late reason"""
        markup = telebot.types.InlineKeyboardMarkup()
        markup.row(
            telebot.types.InlineKeyboardButton("✅ Submit", callback_data=f"submit_{reason}"),
            telebot.types.InlineKeyboardButton("✏️ Edit", callback_data="edit")
        )
        markup.row(telebot.types.InlineKeyboardButton("❌ Cancel", callback_data="cancel"))

        self.bot.send_message(
            chat_id,
            f"Please review your reason for being late:\n\n<b>{reason}</b>\n\nWhat would you like to do?",
            reply_markup=markup,
            parse_mode="html"
        )

    def handle_callback(self, call):
        """Handle callback queries from inline buttons"""
        chat_id = call.message.chat.id
        username = f"@{call.from_user.username}" if call.from_user.username else None
        
        if not username:
            self.bot.answer_callback_query(call.id, "Please set a username in your Telegram settings.")
            return

        if call.data.startswith("submit_"):
            reason = call.data[7:]  # Remove "submit_" prefix
            self.db.update_reason(username, reason)
            self.bot.edit_message_text(
                "Your late reason has been recorded. Thank you!",
                chat_id=chat_id,
                message_id=call.message.message_id
            )
            self.db.clear_awaiting_late_reason(username)

            # Notify teacher
            teacher_chat_id = self.db.get_channel_id('@zh1_yangg')
            if teacher_chat_id:
                self.bot.send_message(
                    teacher_chat_id,
                    f"Late reason received from {username}:\n<b>{reason}</b>",
                    parse_mode="html"
                )

        elif call.data == "edit":
            self.bot.edit_message_text(
                "Please enter your reason again:",
                chat_id=chat_id,
                message_id=call.message.message_id
            )

        elif call.data == "cancel":
            self.bot.edit_message_text(
                "Cancelled. Please provide your reason for being late:",
                chat_id=chat_id,
                message_id=call.message.message_id
            )

    def check_attendance_and_notify(self):
        """Check attendance and notify absent students"""
        today = date.today()
        logger.info(f"Checking attendance for {today}")

        # Get all absent students for today
        absent_students = self.db.get_absent_students(today)
        
        for student in absent_students:
            try:
                chat_id = self.db.get_channel_id(student['username'])
                if chat_id:
                    self.bot.send_message(
                        chat_id,
                        "You have been marked as late for today's class. Please provide a reason:",
                        parse_mode="html"
                    )
                    # Mark student as awaiting late reason
                    self.db.set_awaiting_late_reason(student['username'])
            except Exception as e:
                logger.error(f"Error notifying student {student['username']}: {e}")