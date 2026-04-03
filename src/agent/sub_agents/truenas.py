from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from src.clients.truenas import TrueNASClient
from src.config.settings import settings
from src.agent.prompts import TRUENAS_SYSTEM_PROMPT

# Initialize client
truenas = TrueNASClient()

# Initialize a local LLM instance specifically for sub-agent internal reasoning
sub_agent_llm = ChatOllama(
    base_url=settings.OLLAMA_BASE_URL,
    model=settings.OLLAMA_MODEL,
    temperature=settings.OLLAMA_TEMPERATURE,
    num_ctx=settings.OLLAMA_NUM_CTX
)

@tool
def check_truenas() -> str:
    """Use this tool to get a complete health assessment of the TrueNAS storage server. 
    It checks ZFS pool health, disk SMART status, disk temperatures, and system alerts automatically."""
    
    # 1. Deterministic Data Collection (Gather all TrueNAS info upfront)
    pool_health = truenas.get_pool_health()
    disk_health = truenas.get_disk_health()
    disk_temps = truenas.get_disk_temps()
    alerts = truenas.get_alerts()

    # 2. Package telemetry
    telemetry_context = f"""
    [TRUENAS RAW TELEMETRY DATA]
    1. ZFS Pool Health & Capacity: {pool_health}
    2. Disk Health (S.M.A.R.T.): {disk_health}
    3. Live Disk Temperatures: {disk_temps}
    4. Active System Alerts: {alerts}
    """

    # 3. Call LLM to summarize
    prompt = ChatPromptTemplate.from_messages([
        ("system", TRUENAS_SYSTEM_PROMPT),
        ("user", "Provide a health assessment for TrueNAS based on this telemetry:\n{telemetry}")
    ])

    chain = prompt | sub_agent_llm
    result = chain.invoke({"telemetry": telemetry_context})
    
    return result.content