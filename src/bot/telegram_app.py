import re
import requests
import telebot
from src.config.settings import settings

# Initialize the bot object using your token
bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN)

# ==========================================
# FORMATTING HELPER
# ==========================================
def clean_markdown_for_telegram(text: str) -> str:
    """
    Converts standard AI Markdown (GitHub Flavored) into Telegram's strict Markdown format.
    """
    if not text:
        return text
        
    # 1. Convert LLM double-asterisk bold (**text**) to Telegram single-asterisk bold (*text*)
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    
    # 2. Convert LLM headers (### Header) to Telegram bold (*Header*)
    text = re.sub(r'^###\s+(.*)', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.*)', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.*)', r'*\1*', text, flags=re.MULTILINE)

    # 3. Wrap markdown tables in monospace code blocks so they align perfectly on mobile
    lines = text.split('\n')
    formatted_lines = []
    in_table = False
    
    for line in lines:
        # Check if line is part of a markdown table (starts and ends with |)
        if line.strip().startswith('|') and line.strip().endswith('|'):
            if not in_table:
                formatted_lines.append('```text') # Start code block
                in_table = True
            formatted_lines.append(line)
        else:
            if in_table:
                formatted_lines.append('```') # End code block
                in_table = False
            formatted_lines.append(line)
            
    # Close the table if the message ended while still inside one
    if in_table:
        formatted_lines.append('```')
        
    return '\n'.join(formatted_lines)


# ==========================================
# GOAL 2: The Push Notification (For Cron Jobs)
# ==========================================
def send_telegram_alert(text: str) -> None:
    """
    Used by background scripts (like check_anomalies.py) to push a message 
    directly to the allowed user without needing the daemon to be listening.
    """
    # Clean the text before sending the push alert!
    formatted_text = clean_markdown_for_telegram(text)
    
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_ALLOWED_USER_ID,
        "text": formatted_text,
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
        
        # Import the compiled LangGraph application
        from src.agent.graph import app as agent_app
        
        # Invoke the graph. 
        ai_response = agent_app.invoke({
            "messages": [("user", user_query)],
            "context_data": {} 
        })
        
        # Extract the final message from the state
        last_message = ai_response["messages"][-1]
        
        # 1. Check if the AI skipped the question (Supervisor routed to FINISH)
        if last_message.type == "human":
            reply_text = "I have no action to take for that. (Routed to FINISH)"
        
        # 2. Extract standard AI response
        else:
            reply_text = last_message.content
            
        # 3. Fallback if the local LLM returned an empty string 
        if not reply_text or not str(reply_text).strip():
            print(f"DEBUG: Raw Empty Message Data: {last_message}")
            reply_text = "⚠️ The AI finished its process but returned an empty response. Check your terminal logs."
        
        # --> MAGIC HAPPENS HERE: Format the text right before replying <--
        final_text = clean_markdown_for_telegram(str(reply_text))
        
        bot.reply_to(message, final_text, parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, f"⚠️ *Error processing request:*\n`{str(e)}`", parse_mode="Markdown")


def start_bot_daemon():
    """
    Starts the continuous polling loop to listen for new messages.
    """
    print(f"Starting Telegram Bot Daemon for User ID: {settings.TELEGRAM_ALLOWED_USER_ID}...")
    bot.infinity_polling()