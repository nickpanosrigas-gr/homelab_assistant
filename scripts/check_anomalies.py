import sys
import requests
from src.config.settings import settings

def check_ollama_and_exit():
    """
    Fast-fail check: Pings the Ollama API. 
    If it is unreachable (e.g., Gaming VM shut it down), exit cleanly.
    """
    try:
        # Ollama's root endpoint returns "Ollama is running" with a 200 OK.
        # We use a short 2-second timeout so the cron job fails fast.
        response = requests.get(settings.OLLAMA_BASE_URL, timeout=2)
        response.raise_for_status()
        
    except requests.exceptions.RequestException as e:
        print(f"AI is offline (Ollama unreachable). Canceling job. Reason: {e}")
        sys.exit(0) # Clean exit (0) prevents cron from sending failure emails

if __name__ == "__main__":
    check_ollama_and_exit()
    print("Ollama is online! Proceeding with telemetry checks...")
    
    # TODO: Add Prometheus and Loki checks here