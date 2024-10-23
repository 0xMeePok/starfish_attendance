import logging
from bot import AttendanceBot
from starfishdb import StarfishDB
from dotenv import load_dotenv
from datetime import datetime, time
import time as time_module
import sys

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BotRunner:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Get bot token
        self.db = StarfishDB()
        self.token = self.db.token
        
        if not self.token:
            raise ValueError("Bot token not found!")
            
        self.bot = None

    def run(self):
        try:
            logger.info("Starting bot...")
            self.bot = AttendanceBot(self.token)
            self.bot.run()
            
            # If it's past 10:15, run attendance check
            current_time = datetime.now().time()
            if current_time >= time(10, 15):
                logger.info("It's past 10:15, running attendance check...")
                self.bot.check_attendance_and_notify()

            logger.info("Bot is running. Press Ctrl+C to stop.")
            
            # Keep the script running
            while True:
                time_module.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("\nShutting down...")
            if self.bot:
                self.bot.stop()
        except Exception as e:
            logger.error(f"Error: {e}")
            if self.bot:
                self.bot.stop()
            raise

def main():
    try:
        runner = BotRunner()
        runner.run()
    except Exception as e:
        logger.error(f"Error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()