from typing import Literal
from langchain_core.tools import tool

# Import your raw deterministic tools
from src.tools.ping import PingClient
from src.tools.telemetry import telemetry as fetch_telemetry
from src.tools.truenas import truenas as fetch_truenas

# Assuming you have a query function in your qdrant.py script
#from src.agent.qdrant import query_qdrant 

# Instantiate clients that require it
ping_client = PingClient()

@tool
def ping(service_name: Literal["ollama", "technitium", "jellyfin", "navidrome", "vaultwarden", "nginx"]) -> str:
    """
    Connectivity Tester. Pings the specified service to check if it is online. 
    Automatically tests both local IPs and external domains if applicable.
    """
    return ping_client.ping_service(service_name)

@tool
def telemetry(service_name: str, timeframe: Literal['1h', '24h', '7d'] = '24h') -> str:
    """
    The Fused Telemetry Aggregator. Queries Loki (logs) and InfluxDB (hardware metrics).
    Returns a highly compressed, time-aligned YAML matrix containing hardware anomalies 
    and ERROR/WARN logs for the specified service. 
    """
    return fetch_telemetry(service_name, timeframe)

@tool
def truenas(timeframe: Literal['1h', '24h', '7d'] = '24h') -> str:
    """
    Storage API Client. Pulls TrueNAS zpool health, dataset capacities, disk temperatures, 
    and active alert statuses.
    """
    return fetch_truenas(timeframe)
'''
@tool
def query_knowledge(query: str) -> str:
    """
    RAG Knowledge Engine. Queries the Qdrant vector database for local knowledge base context.
    Use this to find Docker Compose files, Proxmox scripts, application runbooks, network 
    topology, and general homelab setup information.
    """
    return query_qdrant(query)
'''