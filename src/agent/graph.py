from langchain_community.chat_models import ChatOllama
from src.config.settings import settings
import logging

logger = logging.getLogger(__name__)

def get_llm():
    """Initializes the connection to the local Ollama instance."""
    logger.info(f"Connecting to Ollama at {settings.OLLAMA_BASE_URL}")
    return ChatOllama(
        base_url=settings.OLLAMA_BASE_URL,
        model="ibm/granite4:micro-h-q8_0", 
        temperature=0.1 # Low temperature for more factual infrastructure answers
    )

def test_llm_connection():
    """A simple test to see if Ollama responds."""
    try:
        llm = get_llm()
        response = llm.invoke("Say 'Hello, Admin!'")
        print(f"Ollama Response: {response.content}")
        return True
    except Exception as e:
        print(f"Failed to connect to Ollama: {e}")
        return False

if __name__ == "__main__":
    test_llm_connection()