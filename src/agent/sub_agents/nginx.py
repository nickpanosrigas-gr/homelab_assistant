from typing import Literal
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama
from langchain_google_genai import ChatGoogleGenerativeAI

from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient
from src.clients.ping import PingClient
from src.config.settings import settings
from src.agent.prompts import NGINX_SYSTEM_PROMPT, DESC_CHECK_NGINX

# Initialize clients
influx_client = InfluxDBClient()
loki_client = LokiClient()
ping_client = PingClient()

# Initialize a local LLM instance specifically for sub-agent internal reasoning
#sub_agent_llm = ChatOllama(
#    base_url=settings.OLLAMA_BASE_URL,
#    model=settings.OLLAMA_MODEL,
#    temperature=settings.OLLAMA_TEMPERATURE,
#    num_ctx=settings.OLLAMA_NUM_CTX
#)

# --- Google Gemini Setup ---
sub_agent_llm = ChatGoogleGenerativeAI(
    model=settings.GEMINI_MODEL,
    google_api_key=settings.GOOGLE_API_KEY
)

@tool(description=DESC_CHECK_NGINX)
def check_nginx(
    instruction: str, 
    timeframe: Literal['day', 'week', 'month'] = 'day'
) -> str:
    """
    Use this tool to check the health, logs, and metrics of the Nginx Proxy Manager service.
    
    Args:
        instruction: The specific task or question the Main Agent wants answered.
        timeframe: The period of logs and metrics to analyze. Defaults to 'day'.
    """
    print(f"\n[DEBUG SUB-AGENT] NGINX Agent Triggered | Timeframe: {timeframe}")
    print(f"[DEBUG SUB-AGENT] Instruction: {instruction}")
    
    # 1. Deterministic Data Collection
    local_ping = ping_client.ping_service("http://192.168.1.120:81")
    logs = loki_client.get_container_logs("nginx-proxy-manager", timeframe=timeframe)
    metrics = influx_client.get_container_metrics("nginx-proxy-manager", timeframe=timeframe)

    # 2. Package telemetry
    telemetry_context = f"""
    [NGINX PROXY MANAGER RAW TELEMETRY DATA]
    Timeframe Analyzed: Last {timeframe.capitalize()}
    1. Local Admin Panel Reachability: {local_ping}
    2. Container Metrics: {metrics}
    3. Recent Log Activity: {logs}
    """
    
    # 3. Call LLM to execute the Main Agent's instruction
    prompt = ChatPromptTemplate.from_messages([
        ("system", NGINX_SYSTEM_PROMPT),
        ("user", "MAIN AGENT INSTRUCTION: {instruction}\n\nExecute the instruction using the following telemetry data:\n{telemetry}")
    ])

    chain = prompt | sub_agent_llm
    result = chain.invoke({"telemetry": telemetry_context, "instruction": instruction})
    
    # 4. Return the result to the Main Agent
    return result.content