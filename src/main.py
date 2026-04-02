import sys
import logging
from dotenv import load_dotenv

# Ensure environment variables are loaded prior to component initialization
load_dotenv()

from src.bot.telegram_app import start_bot_daemon

# Configure basic logging for the console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Initializing Home Lab AIOps Assistant...")
    logger.info("Hardware constraints active: Will connect to local Ollama LXC.")
    
    try:
        # Start the blocking Telegram polling loop
        start_bot_daemon()
    except KeyboardInterrupt:
        logger.info("\nCaught KeyboardInterrupt. Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error encountered: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()