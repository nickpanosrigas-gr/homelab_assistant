import time
import requests
from src.config.settings import settings

class LokiClient:
    def __init__(self):
        self.url = f"{settings.LOKI_URL}/loki/api/v1/query_range"

    def get_container_logs(self, logql_string: str) -> str:
        """
        Use to fetch system logs for troubleshooting. You must provide a valid LogQL string (no brackets).
        
        ALLOWED INPUT MAPPING:
        - Navidrome = service_name="navidrome-navidrome-1"
        - Vaultwarden = service_name="vaultwarden"
        - Wireguard = service_name="wireguard"
        - Technitium = service_name="technitium"
        - Jellyfin = service_name="jellyfin"
        - Jellyfin Transcoding = service_name="syslog"
        - Nginx Proxy Manager = service_name="nginx-proxy-manager"
        - Cloudflare DDNS = service_name="cloudflare-ddns"
        - Cloudflare Tunnel = service_name="cloudflared"
        - Jellyseerr = service_name="jellyseerr"
        - Deunhealth = service_name="deunhealth"
        - Gluetun = service_name="gluetun"
        - n8n = service_name="n8n"
        - Open WebUI = service_name="open-webui"
        - Radarr = service_name="radarr"
        - Sonarr = service_name="sonarr"
        - Prowlarr = service_name="prowlarr"
        - qBittorrent = service_name="qbittorrent"
        - Grafana = service_name="grafana"
        """
        
        # Calculate start time (30 days ago) in nanoseconds, matching n8n's logic
        thirty_days_ago_ns = int((time.time() - (30 * 24 * 60 * 60)) * 1_000_000_000)

        # Wrap the LLM's raw input in the brackets
        query = f"{{{logql_string}}}"

        params = {
            "query": query,
            "limit": 80,
            "start": str(thirty_days_ago_ns)
        }

        try:
            response = requests.get(self.url, params=params, timeout=10)
            response.raise_for_status()
            
            # Extract just the raw log text so we don't overwhelm the LLM's context window with JSON metadata
            data = response.json()
            results = data.get("data", {}).get("result", [])
            
            if not results:
                return f"No logs found for query: {query}"
                
            formatted_logs = []
            for stream in results:
                for val in stream.get("values", []):
                    # val is usually [timestamp, "log message"]
                    formatted_logs.append(val[1])
                    
            return "\n".join(formatted_logs)
            
        except requests.exceptions.RequestException as e:
            return f"Error fetching logs for {logql_string}: {str(e)}"