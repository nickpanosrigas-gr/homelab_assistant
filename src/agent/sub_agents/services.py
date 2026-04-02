from langchain_core.tools import tool
from src.clients.influxdb import InfluxDBClient
from src.clients.grafana_loki import LokiClient
from src.clients.ping import PingClient

# Initialize our clients
influx_client = InfluxDBClient()
loki_client = LokiClient()
ping_client = PingClient()

@tool
def fetch_service_metrics(service_name: str) -> str:
    """
    Use this tool to fetch the last 24 hours of CPU, RAM, Disk, and Network metrics for Docker or LXC containers.
    
    ALLOWED INPUTS: jellyfin, technitiumdns, ollama, vaultwarden, wireguard, navidrome-navidrome-1, 
    nginx-proxy-manager, cloudflared, cloudflare-ddns, byparr, deunhealth, gluetun, jellyseerr, 
    profilarr, prowlarr, qbittorrent, radarr, sonarr, n8n, n8n-postgres, grafana, prometheus, 
    loki, promtail, telegraf, influxdb, open-webui.
    """
    return influx_client.get_container_metrics(service_name)

@tool
def fetch_service_logs(logql_string: str) -> str:
    """
    Use to fetch system logs for troubleshooting. You must provide a valid LogQL string (no brackets).
    
    ALLOWED INPUT MAPPING:
    - Navidrome = service_name="navidrome-navidrome-1"
    - Vaultwarden = service_name="vaultwarden"
    - Wireguard = service_name="wireguard"
    - Technitium = service_name="technitium"
    - Jellyfin = service_name="jellyfin"
    - Nginx Proxy Manager = service_name="nginx-proxy-manager"
    - n8n = service_name="n8n"
    # ... (Include the rest of your mapping from the Loki client here) ...
    """
    return loki_client.get_container_logs(logql_string)

@tool
def check_service_status(url: str) -> str:
    """
    Use to ping a service to check if it is online via HTTP/HTTPS.
    You must provide the full URL (e.g., http://192.168.1.120:5678).
    """
    return ping_client.ping_service(url)

# Bundle the tools and define the persona for LangGraph
SERVICES_TOOLS = [fetch_service_metrics, fetch_service_logs, check_service_status]

SERVICES_SYSTEM_PROMPT = """You are the Services & Container Specialist for a homelab.
Your job is to diagnose issues with Docker containers and LXC services.
Always check both metrics (CPU/RAM) and logs if a service is acting up. 
Do not guess configurations; use your tools to fetch real data. 
If a service is completely down, use the ping tool to verify network reachability first."""