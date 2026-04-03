from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient
from src.clients.ping import PingClient
from src.config.settings import settings
from src.agent.prompts import JELLYFIN_SYSTEM_PROMPT

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

@tool
def check_jellyfin() -> str:
    """Use this tool to get a complete health assessment of the Jellyfin media server. 
    It checks pings, logs, and container metrics automatically."""
    
    # 1. Deterministic Data Collection
    local_ping = ping_client.ping_service("http://192.168.1.210:8096")
    domain_ping = ping_client.ping_service("https://jellyfin.pali.autos")
    logs = loki_client.get_container_logs("jellyfin")
    metrics = influx_client.get_container_metrics("jellyfin")

    # 2. Package telemetry
    telemetry_context = f"""
    [JELLYFIN RAW TELEMETRY DATA]
    1. Local Network Reachability: {local_ping}
    2. External Domain Reachability: {domain_ping}
    3. Container Metrics (Averages): {metrics}
    4. Recent Log Activity: {logs}
    """

    # 3. Call LLM to summarize
    prompt = ChatPromptTemplate.from_messages([
        ("system", JELLYFIN_SYSTEM_PROMPT),
        ("user", "Provide a health assessment for Jellyfin based on this telemetry:\n{telemetry}")
    ])

    chain = prompt | sub_agent_llm
    result = chain.invoke({"telemetry": telemetry_context})
    
    # 4. Return the summary to the Main Agent
    return result.content