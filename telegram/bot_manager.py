import threading
from datetime import datetime, time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging
from starfishdb import StarfishDB
import telebot
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        self.db = StarfishDB()
        self.bot = telebot.TeleBot(self.db.token)
        self.bot_thread = None
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        
        # Set up timezone
        self.timezone = pytz.timezone('Asia/Singapore')

    def start_bot(self):
        """Start the Telegram bot."""
        if not self.is_running:
            logger.info("Starting Telegram bot...")
            self.is_running = True
            self.bot_thread = threading.Thread(target=self.bot.polling, kwargs={'none_stop': True})
            self.bot_thread.start()
            logger.info("Telegram bot started successfully")

    def stop_bot(self):
        """Stop the Telegram bot."""
        if self.is_running:
            logger.info("Stopping Telegram bot...")
            self.is_running = False
            self.bot.stop_polling()
            if self.bot_thread:
                self.bot_thread.join()
            logger.info("Telegram bot stopped successfully")

    def schedule_bot(self):
        """Schedule the bot to run on Mondays."""
        # Schedule start at 10:15 AM every Monday
        self.scheduler.add_job(
            self.start_bot,
            trigger=CronTrigger(
                day_of_week='mon',
                hour=10,
                minute=15,
                timezone=self.timezone
            ),
            id='start_bot'
        )

        # Schedule stop at 11:59 PM every Monday
        self.scheduler.add_job(
            self.stop_bot,
            trigger=CronTrigger(
                day_of_week='mon',
                hour=23,
                minute=59,
                timezone=self.timezone
            ),
            id='stop_bot'
        )

        # Start the scheduler
        self.scheduler.start()
        logger.info("Bot scheduler started")

    def shutdown(self):
        """Shutdown the bot and scheduler."""
        self.stop_bot()
        self.scheduler.shutdown()
        logger.info("Bot manager shut down completely")