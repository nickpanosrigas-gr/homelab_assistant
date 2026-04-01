import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from src.config.settings import settings

# Set up logging so we can see what's happening in the terminal
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def security_check(update: Update) -> bool:
    """Ensure only the authorized homelab admin can talk to the bot."""
    user_id = update.effective_user.id
    if user_id != settings.TELEGRAM_ALLOWED_USER_ID:
        logger.warning(f"Unauthorized access attempt by user ID: {user_id}")
        return False
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command."""
    if not await security_check(update):
        return
    await update.message.reply_text(
        "🖥️ Homelab AIOps Assistant is online.\n\n"
        "I am connected to Proxmox, TrueNAS, and Docker. How can I help you today?"
    )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles standard text messages (will eventually route to LangGraph)."""
    if not await security_check(update):
        return
    
    user_text = update.message.text
    logger.info(f"Received message: {user_text}")
    
    # TODO: Pass `user_text` to the LangGraph Supervisor!
    # For now, we just echo to prove the bot works.
    await update.message.reply_text(f"Received: {user_text} \n(LangGraph routing coming soon!)")

def build_bot() -> ApplicationBuilder:
    """Constructs and wires up the Telegram application."""
    app = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    
    return app