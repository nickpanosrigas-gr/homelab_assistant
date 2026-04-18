from typing import Literal, Optional
from langchain_core.tools import tool

# Import your raw deterministic tools
from src.tools.ping import PingClient
from src.tools.telemetry import telemetry as fetch_telemetry
from src.tools.truenas import truenas as fetch_truenas
from src.tools.qdrant import query_knowledge

# --- Defined Literals for Strict LLM Typing ---
DomainType = Literal["docker_stack", "lxc", "physical_network", "proxmox_host", "vm"]
ResourceIdType = Literal["110", "120", "130", "200", "210", "220", "host", "network_infrastructure"]
ContentTypeType = Literal["config_file", "docker_compose", "documentation", "network_topology", "script"]
IpAddressType = Literal["192.168.1.100", "192.168.1.110", "192.168.1.120", "192.168.1.130", "192.168.1.200", "192.168.1.210", "192.168.1.220"]
ServiceNameType = Literal["ai", "bios", "cloudflare-ddns", "cloudflared", "cosmote", "cudy", "dns", "docker", "gaming", "gpu_passthrough", "grafana", "grub", "influxdb", "jellyfin", "langfuse", "linuxdocker", "loki", "media", "navidrome", "nginx", "nginx-proxy-manager", "nvidia", "ollama", "open-webui", "promtail", "proxmox", "qdrant", "technitium", "technitiumdns", "telegraf", "truenas", "ubuntu", "vfio", "whisper", "windows", "wireguard", "zfs", "zte"]
# ----------------------------------------------

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

@tool
def qdrant(
    query: str,
    search_size: Literal["normal", "large"] = "normal",
    domain: Optional[DomainType] = None,
    resource_id: Optional[ResourceIdType] = None,
    service_name: Optional[ServiceNameType] = None,
    ip_address: Optional[IpAddressType] = None,
    content_type: Optional[ContentTypeType] = None
) -> str:
    """
    RAG Knowledge Engine. Queries the Qdrant vector database for local knowledge base context.
    Use this to find Docker Compose files, Proxmox scripts, application runbooks, network 
    topology, and general homelab setup information.
    
    Use the optional parameters to strictly filter the results based on known attributes.
    Set search_size to 'large' (8 results) if you need extensive context, otherwise leave as 'normal' (3 results).
    """
    return query_knowledge(
        query=query,
        search_size=search_size,
        domain=domain,
        resource_id=resource_id,
        service_name=service_name,
        ip_address=ip_address,
        content_type=content_type
    )