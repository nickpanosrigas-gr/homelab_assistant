import sys
import logging
from dotenv import load_dotenv

# Ensure environment variables are loaded prior to component initialization
load_dotenv()

from src.bot.telegram_app import start_bot_daemon
# Import the ingestion script's main function
from scripts.ingest_docs import main as ingest_knowledge_base

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
        # Run the RAG ingestion at startup
        logger.info("Executing startup task: Knowledge Base Ingestion...")
        ingest_knowledge_base()
        logger.info("Knowledge Base Ingestion completed successfully.")
        
        # Start the blocking Telegram polling loop
        logger.info("Starting Telegram Bot Daemon...")
        start_bot_daemon()
        
    except KeyboardInterrupt:
        logger.info("\nCaught KeyboardInterrupt. Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error encountered: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()