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
    # Convert standard Markdown bullets (*) into actual bullet characters (•)
    # This stops Telegram from confusing list items with unclosed bold tags.
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
        """Helper to convert accumulated table rows into Telegram-friendly cards."""
        # If it doesn't have a header, separator, and at least one row, return as is.
        if len(buffer) < 3:
            return buffer
            
        # Extract headers (split by '|' and strip whitespace)
        headers = [col.strip() for col in buffer[0].split('|')[1:-1]]
        
        cards = []
        # Skip buffer[1] because it is the markdown separator (e.g., |---|---|)
        for row in buffer[2:]:
            cols = [col.strip() for col in row.split('|')[1:-1]]
            card_lines = []
            
            for i, col_val in enumerate(cols):
                header_name = headers[i] if i < len(headers) else "Data"
                
                # Make the first column act as a "Title" for the item
                if i == 0:
                    card_lines.append(f"🔹 *{col_val}*")
                # Format subsequent columns as indented bullet points
                else:
                    card_lines.append(f"   ▫️ _{header_name}:_ {col_val}")
                    
            cards.append("\n".join(card_lines))
        
        # Return the joined cards with padding
        return ["\n" + "\n\n".join(cards) + "\n"]

    # 2. Iterate through text and catch tables
    for line in lines:
        if line.strip().startswith('|') and line.strip().endswith('|'):
            table_buffer.append(line.strip())
        else:
            if table_buffer:
                # We hit the end of a table, process the buffer
                formatted_lines.extend(process_table_buffer(table_buffer))
                table_buffer = []
            formatted_lines.append(line)
            
    # Flush any remaining table data if the message ends with a table
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
        
        # --- FALLBACK: If Telegram hates the formatting, strip it and try again ---
        if response.status_code == 400 and "parse entities" in response.text.lower():
            print("[DEBUG] Telegram rejected Markdown in alert. Retrying as plain text.")
            payload.pop("parse_mode") 
            payload["text"] = f"⚠️ [Markdown stripped due to formatting error]\n\n{formatted_text}"
            response = requests.post(url, json=payload, timeout=10)
            
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Telegram alert: {e}")


# ==========================================
# SHARED AGENT LOGIC
# ==========================================
def process_query_with_agent(message, user_query: str):
    """
    Shared logic to send text to the LangGraph agent and reply to the user.
    """
    # 1. Start the continuous typing thread
    stop_typing = threading.Event()
    typing_thread = threading.Thread(
        target=keep_chat_action_alive, 
        args=(message.chat.id, stop_typing, 'typing')
    )
    typing_thread.start()

    try:
        from src.agent.graph import app as agent_app
        
        # --- LANGFUSE INTEGRATION (VERSION 2 SHIM) ---
        import sys
        import langchain_core.callbacks.base
        import langchain_core.agents
        import langchain_core.documents
        
        # Inject fake paths into Python's memory so the old Langfuse V2 SDK 
        # can successfully find the modern Langchain V1.x modules
        sys.modules['langchain.callbacks.base'] = langchain_core.callbacks.base
        sys.modules['langchain.schema.agent'] = langchain_core.agents
        sys.modules['langchain.schema.document'] = langchain_core.documents

        # Now the V2 import will succeed without the ModuleNotFoundError!
        from langfuse.callback import CallbackHandler
        
        # Initialize a fresh handler for this specific user's message
        langfuse_handler = CallbackHandler(
            secret_key=settings.LANGFUSE_SECRET_KEY,
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            host=settings.LANGFUSE_HOST,
            user_id=str(message.from_user.id),
            session_id=f"telegram_chat_{message.chat.id}"
        )

        # Invoke the graph with the Langfuse callbacks
        ai_response = agent_app.invoke(
            {
                "messages": [("user", user_query)],
                "context_data": {} 
            },
            config={
                "callbacks": [langfuse_handler]
            }
        )
        # -----------------------------------------
        
        last_message = ai_response["messages"][-1]
        
        if last_message.type == "human":
            reply_text = "I have no action to take for that. (Routed to FINISH)"
        else:
            # --- GEMINI CONTENT PARSING FIX ---
            raw_content = last_message.content
            reply_text = ""
            
            if isinstance(raw_content, list):
                text_parts = []
                for item in raw_content:
                    if isinstance(item, dict) and 'text' in item:
                        text_parts.append(item['text'])
                    elif isinstance(item, str):
                        text_parts.append(item)
                reply_text = "\n".join(text_parts)
            elif isinstance(raw_content, dict) and 'text' in raw_content:
                reply_text = raw_content['text']
            elif isinstance(raw_content, str):
                try:
                    import ast
                    parsed = ast.literal_eval(raw_content)
                    if isinstance(parsed, dict) and 'text' in parsed:
                        reply_text = parsed['text']
                    elif isinstance(parsed, list):
                        text_parts = [
                            item['text'] if isinstance(item, dict) and 'text' in item else str(item)
                            for item in parsed
                        ]
                        reply_text = "\n".join(text_parts)
                    else:
                        reply_text = raw_content
                except (ValueError, SyntaxError):
                    reply_text = raw_content
            else:
                reply_text = str(raw_content)
            # ----------------------------------
            
        if not reply_text or not str(reply_text).strip():
            print(f"DEBUG: Raw Empty Message Data: {last_message}")
            reply_text = "⚠️ The AI finished its process but returned an empty response."
        
        final_text = clean_markdown_for_telegram(str(reply_text))
        
        # --- TELEGRAM FORMATTING FALLBACK ---
        try:
            bot.reply_to(message, final_text, parse_mode="Markdown")
        except Exception as send_err:
            if "can't parse entities" in str(send_err).lower() or "bad request" in str(send_err).lower():
                print(f"[DEBUG] Telegram Markdown parsing failed. Sending plain text. Error: {send_err}")
                bot.reply_to(message, f"⚠️ [Markdown stripped due to formatting error]\n\n{final_text}")
            else:
                raise send_err # It's a real network error, pass it to the main exception block
        # ------------------------------------
        
    except Exception as e:
        # Also protect the error message itself from unclosed formatting
        try:
            bot.reply_to(message, f"⚠️ *Error processing request:*\n`{str(e)}`", parse_mode="Markdown")
        except:
            bot.reply_to(message, f"⚠️ Error processing request:\n{str(e)}")
        
    finally:
        # 2. Guarantee the typing thread stops when the work is done
        stop_typing.set()
        typing_thread.join()
        
# ==========================================
# The Interactive Daemon (For Chatting)
# ==========================================
@bot.message_handler(content_types=['text'])
def handle_incoming_text(message):
    """Listens for incoming text messages."""
    if message.from_user.id != settings.TELEGRAM_ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Unauthorized user. Access denied.")
        return

    process_query_with_agent(message, message.text)


@bot.message_handler(content_types=['voice', 'audio'])
def handle_incoming_voice(message):
    if message.from_user.id != settings.TELEGRAM_ALLOWED_USER_ID:
        bot.reply_to(message, "⛔ Unauthorized user. Access denied.")
        return
    
    # Start continuous "Recording audio..." animation
    stop_recording = threading.Event()
    recording_thread = threading.Thread(
        target=keep_chat_action_alive, 
        args=(message.chat.id, stop_recording, 'record_voice')
    )
    recording_thread.start()
    
    try:
        file_id = message.voice.file_id if message.content_type == 'voice' else message.audio.file_id
        file_info = bot.get_file(file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        transcription = transcribe_audio(downloaded_file)
        
        # Stop recording animation BEFORE sending the text to the agent
        stop_recording.set()
        recording_thread.join()
        
        if not transcription:
            bot.reply_to(message, "⚠️ *Transcription failed:* The audio was empty or the Whisper API is unreachable.", parse_mode="Markdown")
            return
            
        bot.reply_to(message, f"🎙️ *I heard:* _{transcription}_", parse_mode="Markdown")
        
        # This will trigger the agent, which handles its own 'typing' animation!
        process_query_with_agent(message, transcription)
        
    except Exception as e:
        stop_recording.set()
        recording_thread.join()
        bot.reply_to(message, f"⚠️ *Error processing audio:*\n`{str(e)}`", parse_mode="Markdown")

def start_bot_daemon():
    """Starts the continuous polling loop."""
    print(f"Starting Telegram Bot Daemon for User ID: {settings.TELEGRAM_ALLOWED_USER_ID}...")
    bot.infinity_polling()
    
# ==========================================
# CHAT ACTION HELPER
# ==========================================
def keep_chat_action_alive(chat_id, stop_event, action='typing'):
    """
    Telegram automatically cancels chat actions after 5 seconds.
    This thread pulses the action every 4 seconds until the stop_event is triggered.
    """
    while not stop_event.is_set():
        try:
            bot.send_chat_action(chat_id, action)
        except Exception:
            pass # Ignore temporary network blips
        # Wait 4 seconds before sending the next pulse, or break immediately if stop_event is set
        stop_event.wait(4)