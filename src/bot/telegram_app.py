import re
import requests
import telebot
import threading
import ast  # Imported to safely parse stringified dictionaries
from src.config.settings import settings
from src.bot.whisper_stt import transcribe_audio  # Import the new transcription module

# Initialize the bot object using your token
bot = telebot.TeleBot(settings.TELEGRAM_BOT_TOKEN)

# ==========================================
# THREAD TRACKING MAP
# ==========================================
# Maps a Telegram Bot's message ID to a LangGraph thread ID
MESSAGE_THREAD_MAP = {}

# ==========================================
# FORMATTING HELPER
# ==========================================
def clean_markdown_for_telegram(text: str) -> str:
    """
    Converts standard AI Markdown (GitHub Flavored) into Telegram's strict Markdown format.
    Automatically intercepts Markdown tables and converts them into mobile-friendly lists.
    """
    if not text:
        return text
        
    # --- NEW FIX: Handle bullet points BEFORE formatting ---
    text = re.sub(r'^(\s*)\*\s+', r'\1• ', text, flags=re.MULTILINE)
        
    # 1. Handle standard Markdown to Telegram Markdown conversions
    text = re.sub(r'\*\*(.*?)\*\*', r'*\1*', text)
    text = re.sub(r'^###\s+(.*)', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^##\s+(.*)', r'*\1*', text, flags=re.MULTILINE)
    text = re.sub(r'^#\s+(.*)', r'*\1*', text, flags=re.MULTILINE)

    lines = text.split('\n')
    formatted_lines = []
    
    table_buffer = []
    
    def process_table_buffer(buffer):
        if len(buffer) < 3:
            return buffer
        headers = [col.strip() for col in buffer[0].split('|')[1:-1]]
        cards = []
        for row in buffer[2:]:
            cols = [col.strip() for col in row.split('|')[1:-1]]
            card_lines = []
            for i, col_val in enumerate(cols):
                header_name = headers[i] if i < len(headers) else "Data"
                if i == 0:
                    card_lines.append(f"🔹 *{col_val}*")
                else:
                    card_lines.append(f"   ▫️ _{header_name}:_ {col_val}")
            cards.append("\n".join(card_lines))
        return ["\n" + "\n\n".join(cards) + "\n"]

    for line in lines:
        if line.strip().startswith('|') and line.strip().endswith('|'):
            table_buffer.append(line.strip())
        else:
            if table_buffer:
                formatted_lines.extend(process_table_buffer(table_buffer))
                table_buffer = []
            formatted_lines.append(line)
            
    if table_buffer:
        formatted_lines.extend(process_table_buffer(table_buffer))
        
    return '\n'.join(formatted_lines)

# ==========================================
# The Push Notification (For Cron Jobs)
# ==========================================
def send_telegram_alert(text: str) -> None:
    formatted_text = clean_markdown_for_telegram(text)
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_ALLOWED_USER_ID,
        "text": formatted_text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 400 and "parse entities" in response.text.lower():
            print("[DEBUG] Telegram rejected Markdown in alert. Retrying as plain text.")
            payload.pop("parse_mode") 
            payload["text"] = f"⚠️ [Markdown stripped]\n\n{formatted_text}"
            response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Telegram alert: {e}")


# ==========================================
# SHARED AGENT LOGIC
# ==========================================
def process_query_with_agent(message, user_query: str):
    """
    Shared logic with added debug logging for thread tracking.
    """
    # --- DEBUG: Thread Resolution ---
    print(f"\n[DEBUG TELEGRAM] Incoming from User {message.from_user.id}: '{user_query}'")
    
    if message.reply_to_message:
        print(f"[DEBUG TELEGRAM] User is replying to message ID: {message.reply_to_message.message_id}")
        if message.reply_to_message.message_id in MESSAGE_THREAD_MAP:
            thread_id = MESSAGE_THREAD_MAP[message.reply_to_message.message_id]
            print(f"[DEBUG TELEGRAM] Found existing Thread ID: {thread_id}")
        else:
            thread_id = str(message.message_id)
            print(f"[DEBUG TELEGRAM] No existing thread for this reply. Starting New Thread ID: {thread_id}")
    else:
        thread_id = str(message.message_id)
        print(f"[DEBUG TELEGRAM] New interaction. Starting Thread ID: {thread_id}")

    stop_typing = threading.Event()
    typing_thread = threading.Thread(
        target=keep_chat_action_alive, 
        args=(message.chat.id, stop_typing, 'typing')
    )
    typing_thread.start()

    try:
        from src.agent.graph import app as agent_app
        
        # --- LANGFUSE SHIM ---
        import sys
        import langchain_core.callbacks.base
        import langchain_core.agents
        import langchain_core.documents
        sys.modules['langchain.callbacks.base'] = langchain_core.callbacks.base
        sys.modules['langchain.schema.agent'] = langchain_core.agents
        sys.modules['langchain.schema.document'] = langchain_core.documents
        from langfuse.callback import CallbackHandler
        
        langfuse_handler = CallbackHandler(
            secret_key=settings.LANGFUSE_SECRET_KEY,
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            host=settings.LANGFUSE_HOST,
            user_id=str(message.from_user.id),
            session_id=f"telegram_{thread_id}"
        )

        # --- DEBUG: Agent Invocation ---
        print(f"[DEBUG TELEGRAM] Invoking Agent Thread {thread_id}...")
        ai_response = agent_app.invoke(
            {"messages": [("user", user_query)], "context_data": {}},
            config={
                "callbacks": [langfuse_handler],
                "configurable": {"thread_id": thread_id}
            }
        )
        
        # Log tool calls if any
        all_messages = ai_response["messages"]
        tool_calls = [m for m in all_messages if hasattr(m, 'tool_calls') and m.tool_calls]
        if tool_calls:
            print(f"[DEBUG TELEGRAM] Agent triggered {len(tool_calls)} tool(s).")

        last_message = all_messages[-1]
        
        if last_message.type == "human":
            reply_text = "I have no action to take for that."
        else:
            raw_content = last_message.content
            reply_text = ""
            if isinstance(raw_content, list):
                reply_text = "\n".join([item['text'] if isinstance(item, dict) else str(item) for item in raw_content])
            elif isinstance(raw_content, str):
                reply_text = raw_content
            else:
                reply_text = str(raw_content)
            
        if not reply_text.strip():
            reply_text = "⚠️ The AI returned an empty response."
        
        final_text = clean_markdown_for_telegram(str(reply_text))
        
        # --- DEBUG: Sending and Mapping ---
        try:
            sent_msg = bot.reply_to(message, final_text, parse_mode="Markdown")
            MESSAGE_THREAD_MAP[sent_msg.message_id] = thread_id
            print(f"[DEBUG TELEGRAM] Sent Bot Message ID {sent_msg.message_id} mapped to Thread {thread_id}")
        except Exception as send_err:
            print(f"[DEBUG TELEGRAM] Markdown Send Error: {send_err}")
            sent_msg = bot.reply_to(message, f"⚠️ [Format Error Retrying...]\n\n{final_text}")
            MESSAGE_THREAD_MAP[sent_msg.message_id] = thread_id
        
    except Exception as e:
        print(f"[DEBUG TELEGRAM] CRITICAL ERROR: {str(e)}")
        bot.reply_to(message, f"⚠️ *Error:*\n`{str(e)}`", parse_mode="Markdown")
        
    finally:
        stop_typing.set()
        typing_thread.join()
        
# ==========================================
# Handlers
# ==========================================
@bot.message_handler(content_types=['text'])
def handle_incoming_text(message):
    if message.from_user.id != settings.TELEGRAM_ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    process_query_with_agent(message, message.text)

@bot.message_handler(content_types=['voice', 'audio'])
def handle_incoming_voice(message):
    if message.from_user.id != settings.TELEGRAM_ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Access denied.")
        return
    
    stop_recording = threading.Event()
    recording_thread = threading.Thread(target=keep_chat_action_alive, args=(message.chat.id, stop_recording, 'record_voice'))
    recording_thread.start()
    
    try:
        file_id = message.voice.file_id if message.content_type == 'voice' else message.audio.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        transcription = transcribe_audio(downloaded_file)
        
        stop_recording.set()
        recording_thread.join()
        
        if not transcription:
            bot.reply_to(message, "⚠️ Transcription failed.")
            return
            
        bot.reply_to(message, f"🎙️ *I heard:* _{transcription}_", parse_mode="Markdown")
        process_query_with_agent(message, transcription)
        
    except Exception as e:
        stop_recording.set()
        recording_thread.join()
        print(f"[DEBUG TELEGRAM] Voice Error: {e}")
        bot.reply_to(message, f"⚠️ Audio Error: {str(e)}")

def start_bot_daemon():
    print(f"Starting Telegram Bot Daemon for User ID: {settings.TELEGRAM_ALLOWED_USER_ID}...")
    bot.infinity_polling()
    
def keep_chat_action_alive(chat_id, stop_event, action='typing'):
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, action)
        except Exception:
            pass
        stop_event.wait(4)