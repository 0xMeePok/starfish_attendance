import logging
from bot import AttendanceBot
import os
from datetime import datetime, time
import pytz

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        logger.info("Initializing BotManager...")
        self.token = os.getenv('BOT_TOKEN')
        if not self.token:
            logger.error("BOT_TOKEN not found in environment variables")
            raise ValueError("BOT_TOKEN not found in environment variables")
        
        logger.info("Bot token found")
        self.bot = None
        self.is_running = False
        self.timezone = pytz.timezone('Asia/Singapore')
        logger.info("BotManager initialized successfully")

    def start_bot(self):
        """Start the Telegram bot."""
        try:
            logger.info("Starting bot process...")
            
            if self.is_running:
                logger.info("Bot is already running")
                return
            
            logger.info("Creating new AttendanceBot instance...")
            self.bot = AttendanceBot(self.token)
            
            logger.info("Calling bot.run()...")
            self.bot.run()
            
            self.is_running = True
            logger.info("Bot started successfully")
            
            # Check attendance if it's past 10:15
            current_time = datetime.now(self.timezone).time()
            if current_time >= time(10, 15):
                logger.info("It's past 10:15, running attendance check...")
                self.bot.check_attendance_and_notify()
                
        except Exception as e:
            logger.error(f"Error in start_bot: {e}", exc_info=True)
            self.is_running = False
            raise

    def stop_bot(self):
        """Stop the Telegram bot."""
        try:
            logger.info("Attempting to stop bot...")
            if self.is_running and self.bot:
                logger.info("Calling bot.stop()...")
                self.bot.stop()
                self.is_running = False
                logger.info("Bot stopped successfully")
            else:
                logger.info("Bot was not running")
        except Exception as e:
            logger.error(f"Error in stop_bot: {e}", exc_info=True)
            raise

    def shutdown(self):
        """Clean shutdown of the bot."""
        logger.info("Shutting down bot manager...")
        try:
            self.stop_bot()
            self.bot = None
            logger.info("Bot manager shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)
            raise