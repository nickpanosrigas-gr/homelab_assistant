import concurrent.futures
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient
from src.clients.ping import PingClient
from src.config.settings import settings
from src.agent.prompts import NAVIDROME_SYSTEM_PROMPT, DESC_CHECK_NAVIDROME

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

@tool(description=DESC_CHECK_NAVIDROME)
def check_navidrome(instruction: str) -> str:

    # 1. Deterministic Data Collection - PARALLELIZED
    # We use a ThreadPoolExecutor to run all network requests concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        # Submit all tasks to the thread pool simultaneously
        future_local_ping = executor.submit(ping_client.ping_service, "http://192.168.1.120:4533")
        future_domain_ping = executor.submit(ping_client.ping_service, "https://navidrome.pali.autos")
        future_logs = executor.submit(loki_client.get_container_logs, "navidrome-navidrome-1")
        future_metrics = executor.submit(influx_client.get_container_metrics, "navidrome-navidrome-1")

        # Retrieve the results as soon as they finish
        local_ping = future_local_ping.result()
        domain_ping = future_domain_ping.result()
        logs = future_logs.result()
        metrics = future_metrics.result()

    # 2. Package telemetry
    telemetry_context = f"""
    [NAVIDROME RAW TELEMETRY DATA]
    1. Local Network Reachability: {local_ping}
    2. External Domain Reachability: {domain_ping}
    3. Container Metrics (Averages): {metrics}
    4. Recent Log Activity: {logs}
    """

    # 3. Inject the Main Agent's instruction into the prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", NAVIDROME_SYSTEM_PROMPT),
        ("user", "MAIN AGENT INSTRUCTION: {instruction}\n\nExecute the instruction using the following telemetry data:\n{telemetry}")
    ])

    chain = prompt | sub_agent_llm
    result = chain.invoke({"telemetry": telemetry_context, "instruction": instruction})
    
    return result.content