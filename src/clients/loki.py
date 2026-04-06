import time
import requests
from src.config.settings import settings

class LokiClient:
    def __init__(self):
        self.url = f"{settings.LOKI_URL}/loki/api/v1/query_range"

    def get_container_logs(self, logql_string: str) -> str:
        """
        Use to fetch system logs for troubleshooting. You must provide the exact service name.
        """
        
        print(f"\n[DEBUG LOKI] AI Input: {repr(logql_string)}")
        
        # Fetch only the last 24 Hours
        twenty_four_hours_ago_ns = int((time.time() - (24 * 60 * 60)) * 1_000_000_000)

        clean_service_name = logql_string.strip()
        
        # LogQL Noise Filtering
        query = f'{{service_name="{clean_service_name}"}} != "healthcheck" != "DEBUG"'
        
        print(f"[DEBUG LOKI] Constructed Query: {query}")

        params = {
            "query": query,
            "limit": 100,
            "start": str(twenty_four_hours_ago_ns),
            "direction": "backward"
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
                return f"No logs found for service: {clean_service_name} in the last 24 hours."
                
            formatted_logs = []
            seen_logs = set()
            
            for stream in results:
                for val in stream.get("values", []):
                    log_line = val[1].strip()
                    
                    if not log_line:
                        continue
                        
                    # Deduplication
                    if log_line in seen_logs:
                        continue
                        
                    seen_logs.add(log_line)
                    formatted_logs.append(log_line)
            
            # Chronological Sorting
            formatted_logs.reverse()

            print(f"[DEBUG LOKI] Successfully fetched {len(formatted_logs)} unique log lines.")        
            return "\n".join(formatted_logs)
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching logs for {clean_service_name}: {str(e)}"
            print(f"[DEBUG LOKI] EXCEPTION CAUGHT: {error_msg}")
            return error_msg