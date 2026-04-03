import requests
from src.config.settings import settings

def transcribe_audio(audio_bytes: bytes, filename: str = "voice_message.ogg") -> str:
    """
    Sends audio bytes to the local Speaches (Whisper) API for transcription.
    """
    url = settings.WHISPER_API_URL
    
    # The API expects a multipart/form-data payload
    files = {
        'file': (filename, audio_bytes, 'audio/ogg')
    }
    
    data = {
        # This string tells Speaches exactly which folder to load from your disk!
        'model': settings.WHISPER_MODEL
    }
    
    try:
        # Give it a 60-second timeout just in case it takes a moment to load the model into memory
        response = requests.post(url, files=files, data=data, timeout=60)
        response.raise_for_status()
        
        # Extract the transcribed text from the JSON response
        result = response.json()
        return result.get("text", "").strip()
        
    except requests.exceptions.RequestException as e:
        print(f"Transcription API error: {e}")
        return ""