from typing import Literal
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI

from src.clients.truenas import TrueNASClient
from src.config.settings import settings
from src.agent.prompts import TRUENAS_SYSTEM_PROMPT

# Initialize client
truenas = TrueNASClient()

# Initialize a local LLM instance specifically for sub-agent internal reasoning
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

@tool
def check_truenas(
    instruction: str, 
    timeframe: Literal['day', 'week', 'month'] = 'day'
) -> str:
    """
    Use this tool to get a complete health assessment of the TrueNAS storage server. 
    It checks ZFS pool health, disk SMART status, disk temperatures, and system alerts.
    
    Args:
        instruction: The specific task or question the Main Agent wants answered.
        timeframe: The period to evaluate for historical disk temperatures. Defaults to 'day'.
    """
    
    print(f"\n[DEBUG SUB-AGENT] TrueNAS Agent Triggered | Timeframe: {timeframe}")
    print(f"[DEBUG SUB-AGENT] Instruction: {instruction}")
    
    # 1. Deterministic Data Collection
    pool_health = truenas.get_pool_health()
    disk_health = truenas.get_disk_health()
    disk_temps = truenas.get_disk_temps(timeframe=timeframe)
    alerts = truenas.get_alerts()

    # 2. Package telemetry
    telemetry_context = f"""
    [TRUENAS RAW TELEMETRY DATA]
    Timeframe Analyzed: Last {timeframe.capitalize()}
    
    1. ZFS Pool Health & Capacity: 
    {pool_health}
    
    2. Disk Health (S.M.A.R.T.): 
    {disk_health}
    
    3. Disk Temperatures (Live vs Historical Peak): 
    {disk_temps}
    
    4. Active System Alerts: 
    {alerts}
    """

    # 3. Call LLM to summarize based on Main Agent's instruction
    prompt = ChatPromptTemplate.from_messages([
        ("system", TRUENAS_SYSTEM_PROMPT),
        ("user", "MAIN AGENT INSTRUCTION: {instruction}\n\nExecute the instruction using the following telemetry data:\n{telemetry}")
    ])

    chain = prompt | sub_agent_llm
    result = chain.invoke({"telemetry": telemetry_context, "instruction": instruction})
    
    return result.content