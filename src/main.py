from src.bot.telegram_app import build_bot
import logging

logger = logging.getLogger(__name__)

def main():
    logger.info("Initializing Homelab Assistant Telegram Daemon...")
    
    try:
        bot_app = build_bot()
        logger.info("Bot is polling for messages. Press Ctrl+C to stop.")
        # This starts the bot and blocks the script from exiting
        bot_app.run_polling()
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == "__main__":
    main()