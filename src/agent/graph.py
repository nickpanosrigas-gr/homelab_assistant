from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent

from src.config.settings import settings
from src.agent.state import AssistantState
from src.agent.prompts import MAIN_AGENT_SYSTEM_PROMPT

# Import your deterministic sub-agent tools
from src.agent.sub_agents.jellyfin import check_jellyfin
from src.agent.sub_agents.navidrome import check_navidrome
from src.agent.sub_agents.nginx import check_nginx
from src.agent.sub_agents.vaultwarden import check_vaultwarden
from src.agent.sub_agents.truenas import check_truenas
from src.agent.sub_agents.technitium import check_technitium

# Initialize the Main LLM
# --- Ollama Setup ---
# llm = ChatOllama(
#     base_url=settings.OLLAMA_BASE_URL,
#     model=settings.OLLAMA_MODEL,
#     temperature=settings.OLLAMA_TEMPERATURE,
#     num_ctx=settings.OLLAMA_NUM_CTX
# )

# --- Google Gemini Setup ---
llm = ChatGoogleGenerativeAI(
    model=settings.GEMINI_MODEL,
    google_api_key=settings.GOOGLE_API_KEY
)

# List of tools the Main Agent can choose from
tools = [
    check_jellyfin,
    check_navidrome,
    check_vaultwarden,
    check_nginx,
    check_truenas,
    check_technitium
]

# create_react_agent automatically compiles the StateGraph for us
app = create_react_agent(
    model=llm,
    tools=tools,
    prompt=MAIN_AGENT_SYSTEM_PROMPT,
    state_schema=AssistantState # Preserves your custom context_data fields
)