from typing import Literal
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient
from src.clients.ping import PingClient
from src.config.settings import settings
from src.agent.prompts import TECHNITIUM_SYSTEM_PROMPT, DESC_CHECK_TECHNITIUM

# Initialize clients
influx_client = InfluxDBClient()
loki_client = LokiClient()
ping_client = PingClient()

# Initialize a local LLM instance specifically for sub-agent internal reasoning
sub_agent_llm = ChatOllama(
    base_url=settings.OLLAMA_BASE_URL,
    model=settings.OLLAMA_MODEL,
    temperature=settings.OLLAMA_TEMPERATURE,
    num_ctx=settings.OLLAMA_NUM_CTX
)

@tool(description=DESC_CHECK_TECHNITIUM)
def check_technitium(
    instruction: str, 
    timeframe: Literal['day', 'week', 'month'] = 'day'
) -> str:
    """
    Use this tool to check the health, logs, and metrics of the Technitium DNS service.
    
    Args:
        instruction: The specific task or question the Main Agent wants answered.
        timeframe: The period of logs and metrics to analyze. Defaults to 'day'.
    """
    print(f"\n[DEBUG SUB-AGENT] Technitium Agent Triggered | Timeframe: {timeframe}")
    print(f"[DEBUG SUB-AGENT] Instruction: {instruction}")
    
    # 1. Deterministic Data Collection
    local_ping = ping_client.ping_service("http://192.168.1.200:5380")
    logs = loki_client.get_container_logs("technitium", timeframe=timeframe)
    metrics = influx_client.get_container_metrics("technitiumdns", timeframe=timeframe)

    # 2. Package telemetry
    telemetry_context = f"""
    [TECHNITIUM DNS RAW TELEMETRY DATA]
    Timeframe Analyzed: Last {timeframe.capitalize()}
    1. Local Admin Panel Reachability: {local_ping}
    2. Container Metrics: {metrics}
    3. Recent Log Activity: {logs}
    """

    # 3. Call LLM to execute the Main Agent's instruction
    prompt = ChatPromptTemplate.from_messages([
        ("system", TECHNITIUM_SYSTEM_PROMPT),
        ("user", "MAIN AGENT INSTRUCTION: {instruction}\n\nExecute the instruction using the following telemetry data:\n{telemetry}")
    ])

    chain = prompt | sub_agent_llm
    result = chain.invoke({"telemetry": telemetry_context, "instruction": instruction})
    
    return result.content