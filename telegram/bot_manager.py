import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BotManager:
    def __init__(self):
        self.bot = None
        self.is_running = False
        self.scheduler = None

    def start_bot(self):
        """Start the bot"""
        if not self.is_running:
            # Initialize and start your bot here
            self.is_running = True
            logger.info("Bot started")

    def stop_bot(self):
        """Stop the bot"""
        if self.is_running:
            # Stop your bot here
            self.is_running = False
            logger.info("Bot stopped")

    def shutdown(self):
        """Complete shutdown of bot manager"""
        self.stop_bot()
        logger.info("Bot manager shut down")