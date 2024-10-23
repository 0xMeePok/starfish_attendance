import logging
from bot import AttendanceBot
from starfishdb import StarfishDB
import os
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    try:
        # Load environment variables
        load_dotenv()
        
        # Get bot token
        db = StarfishDB()
        token = db.token
        
        if not token:
            raise ValueError("Bot token not found!")

        logger.info("Starting bot...")
        bot = AttendanceBot(token)
        bot.run()
        
        # Keep the script running
        logger.info("Bot is running. Press Ctrl+C to stop.")
        while True:
            import time
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        if 'bot' in locals():
            bot.stop()
    except Exception as e:
        logger.error(f"Error: {e}")
        if 'bot' in locals():
            bot.stop()

if __name__ == "__main__":
    main()