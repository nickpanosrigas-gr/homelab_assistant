from langchain_core.tools import tool
from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient
from src.clients.ping import PingClient
from src.agent import prompts

influx_client = InfluxDBClient()
loki_client = LokiClient()
ping_client = PingClient()

@tool(description=prompts.DESC_FETCH_METRICS)
def fetch_service_metrics(service_name: str) -> str:
    return influx_client.get_container_metrics(service_name)

@tool(description=prompts.DESC_FETCH_LOGS)
def fetch_service_logs(logql_string: str) -> str:
    return loki_client.get_container_logs(logql_string)

@tool(description=prompts.DESC_CHECK_STATUS)
def check_service_status(url: str) -> str:
    return ping_client.ping_service(url)

SERVICES_TOOLS = [fetch_service_metrics, fetch_service_logs, check_service_status]
SERVICES_SYSTEM_PROMPT = prompts.SERVICES_SYSTEM_PROMPT