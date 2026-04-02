import requests
import telebot
from src.config.settings import settings

# Initialize the bot object using your token
bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN)

# ==========================================
# GOAL 2: The Push Notification (For Cron Jobs)
# ==========================================
def send_telegram_alert(text: str) -> None:
    """
    Used by background scripts (like check_anomalies.py) to push a message 
    directly to the allowed user without needing the daemon to be listening.
    """
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_ALLOWED_USER_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Telegram alert: {e}")


# ==========================================
# GOAL 1: The Interactive Daemon (For Chatting)
# ==========================================
@bot.message_handler(content_types=['text'])
def handle_incoming_text(message):
    """
    Listens for incoming text messages. Validates the user, passes the text 
    to the LangGraph agent, and replies with the result.
    """
    # Security Check: Ignore messages from anyone except you
    if message.from_user.id != settings.TELEGRAM_ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Unauthorized user. Access denied.")
        return

    # Show the "typing..." indicator in Telegram so you know the AI is thinking
    bot.send_chat_action(message.chat.id, 'typing')

    try:
        user_query = message.text
        
        # ---------------------------------------------------------
        # TODO: LangGraph Integration goes here in the next step!
        # Example of how it will look:
        #
        # from src.agent.graph import app as agent_app
        # ai_response = agent_app.invoke({"messages": [("user", user_query)]})
        # reply_text = ai_response["messages"][-1].content
        # ---------------------------------------------------------
        
        # Placeholder reply until we build the agent.py file
        reply_text = f"🤖 *Agent Stub:* I received your message: '{user_query}'. (LangGraph integration pending)."
        
        bot.reply_to(message, reply_text, parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, f"⚠️ *Error processing request:*\n`{str(e)}`", parse_mode="Markdown")


def start_bot_daemon():
    """
    Starts the continuous polling loop to listen for new messages.
    This will block the main thread and keep the script running.
    """
    print(f"Starting Telegram Bot Daemon for User ID: {settings.TELEGRAM_ALLOWED_USER_ID}...")
    # infinity_polling automatically handles reconnects if your internet drops
    bot.infinity_polling()