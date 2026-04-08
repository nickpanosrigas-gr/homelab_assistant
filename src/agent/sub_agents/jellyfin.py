from typing import Literal
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient
from src.clients.ping import PingClient
from src.config.settings import settings
from src.agent.prompts import JELLYFIN_SYSTEM_PROMPT, DESC_CHECK_JELLYFIN

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

@tool(description=DESC_CHECK_JELLYFIN)
def check_jellyfin(
    instruction: str, 
    timeframe: Literal['day', 'week', 'month'] = 'day'
) -> str:
    """
    Use this tool to check the health, logs, and metrics of the Jellyfin service.
    
    Args:
        instruction: The specific task or question the Main Agent wants answered.
        timeframe: The period of logs and metrics to analyze. Defaults to 'day'.
    """
    
    print(f"\n[DEBUG SUB-AGENT] Jellyfin Agent Triggered | Timeframe: {timeframe}")
    print(f"[DEBUG SUB-AGENT] Instruction: {instruction}")

    # 1. Deterministic Data Collection
    local_ping = ping_client.ping_service("http://192.168.1.210:8096")
    domain_ping = ping_client.ping_service("https://jellyfin.pali.autos")
    
    # Logs and Metrics now strictly obey the Main Agent's timeframe request
    app_logs = loki_client.get_container_logs("jellyfin", timeframe=timeframe)
    transcoding_logs = loki_client.get_container_logs("syslog", timeframe=timeframe)
    metrics = influx_client.get_container_metrics("jellyfin", timeframe=timeframe)

    # 2. Package telemetry
    telemetry_context = f"""
    [JELLYFIN RAW TELEMETRY DATA]
    Timeframe Analyzed: Last {timeframe.capitalize()}
    1. Local Network Reachability: {local_ping}
    2. External Domain Reachability: {domain_ping}
    3. Container Metrics: {metrics}
    4. Recent App Logs: {app_logs}
    5. Recent Transcoding Logs (syslog): {transcoding_logs}
    """

    # 3. Call LLM to execute the Main Agent's instruction
    prompt = ChatPromptTemplate.from_messages([
        ("system", JELLYFIN_SYSTEM_PROMPT),
        ("user", "MAIN AGENT INSTRUCTION: {instruction}\n\nExecute the instruction using the following telemetry data:\n{telemetry}")
    ])

    chain = prompt | sub_agent_llm
    result = chain.invoke({"telemetry": telemetry_context, "instruction": instruction})
    
    # 4. Return the result to the Main Agent
    return result.content