import requests
import sys
import os

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://192.168.1.220:11434")

def check_ollama_availability():
    """Pings the Ollama server to see if it is awake and ready."""
    print("Gatekeeper: Checking if Ollama is available...")
    try:
        # A simple GET request to the base URL will return "Ollama is running"
        response = requests.get(OLLAMA_BASE_URL, timeout=3)
        
        if response.status_code == 200:
            print("Gatekeeper: Ollama is online. Waking up the LangGraph Agents...\n")
            return True
            
    except requests.exceptions.RequestException:
        # This catches Timeouts, ConnectionRefused, and NetworkUnreachable errors
        print("Gatekeeper: Ollama is offline (Gaming Mode active or LXC is down).")
        print("Gatekeeper: Exiting script gracefully to prevent crashes.")
        sys.exit(0) # Exits the Python script cleanly with no errors

# --------------------------------------------------------------
# Execution
# --------------------------------------------------------------
if __name__ == "__main__":
    # 1. Run the Gatekeeper first
    check_ollama_availability()
    
    # 2. If the script didn't exit, proceed with the AI investigation
    print("Agent is investigating...")
    
    # ... (Your LangGraph execution code goes here) ...