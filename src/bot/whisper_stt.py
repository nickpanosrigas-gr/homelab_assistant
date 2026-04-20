import requests
from src.config.settings import settings

def transcribe_audio(audio_bytes: bytes, filename: str = "voice_message.ogg") -> str:
    """
    Sends audio bytes to the local Faster-Whisper API for transcription.
    """
    url = settings.WHISPER_API_URL
    
    # The API expects a multipart/form-data payload
    files = {
        'file': (filename, audio_bytes, 'audio/ogg')
    }
    
    data = {
        # This matches the 'model_size: str = Form(...)' in our FastAPI server
        'model_size': settings.WHISPER_MODEL,
        # This explicitly tells the API to skip auto-detect and use English
        'language': settings.WHISPER_LANGUAGE
    }
    
    try:
        # 60-second timeout allows time to load large-v3 into VRAM for the first time
        response = requests.post(url, files=files, data=data, timeout=60)
        response.raise_for_status()
        
        # Extract the transcribed text from the JSON response
        result = response.json()
        return result.get("text", "").strip()
        
    except requests.exceptions.RequestException as e:
        print(f"Transcription API error: {e}")
        return ""