import time
import requests
from src.config.settings import settings

class LokiClient:
    def __init__(self):
        self.url = f"{settings.LOKI_URL}/loki/api/v1/query_range"

    def get_container_logs(self, logql_string: str) -> str:
        """
        Use to fetch system logs for troubleshooting. You must provide the exact service name.
        
        ALLOWED INPUT MAPPING:
        - Navidrome = navidrome-navidrome-1
        - Vaultwarden = vaultwarden
        - Wireguard = wireguard
        - Technitium = technitium
        - Jellyfin = jellyfin
        ... (etc)
        """
        
        # DEBUG: See exactly what the AI passed in
        print(f"\n[DEBUG LOKI] AI Input: {repr(logql_string)}")
        
        # Calculate start time (30 days ago) in nanoseconds
        thirty_days_ago_ns = int((time.time() - (30 * 24 * 60 * 60)) * 1_000_000_000)

        # Strip any accidental whitespace the AI might have added
        clean_service_name = logql_string.strip()
        
        # Build the proper LogQL syntax in python
        # This creates: {service_name="clean_service_name"}
        query = f'{{service_name="{clean_service_name}"}}'
        
        print(f"[DEBUG LOKI] Constructed Query: {query}")

        params = {
            "query": query,
            "limit": 80,
            "start": str(thirty_days_ago_ns)
        }

        try:
            print(f"[DEBUG LOKI] Making request to: {self.url} with params: {params}")
            
            response = requests.get(self.url, params=params, timeout=10)
            
            if response.status_code != 200:
                print(f"[DEBUG LOKI] Raw Error Response: {response.text}")
                
            response.raise_for_status()
            
            data = response.json()
            results = data.get("data", {}).get("result", [])
            
            if not results:
                print("[DEBUG LOKI] Request succeeded, but Loki returned 0 lines.")
                return f"No logs found for service: {clean_service_name}"
                
            formatted_logs = []
            for stream in results:
                for val in stream.get("values", []):
                    formatted_logs.append(val[1])
            
            print(f"[DEBUG LOKI] Successfully fetched {len(formatted_logs)} log lines.")        
            return "\n".join(formatted_logs)
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching logs for {clean_service_name}: {str(e)}"
            print(f"[DEBUG LOKI] EXCEPTION CAUGHT: {error_msg}")
            return error_msg