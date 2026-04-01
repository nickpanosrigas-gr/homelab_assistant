import requests
import time
from typing import Dict, Any, List
from src.config.settings import settings

class LokiClient:
    """API wrapper for querying Grafana Loki logs."""

    def __init__(self):
        self.base_url = settings.LOKI_URL
        self.query_endpoint = f"{self.base_url}/loki/api/v1/query_range"

    def query_logs(self, logql_query: str, limit: int = 100, hours_back: int = 1) -> List[Dict[str, Any]]:
        """
        Execute a LogQL query to fetch recent logs.
        Example: query_logs('{container="jellyfin"} |= "error"')
        """
        # Calculate time range
        end_time = int(time.time() * 1e9) # Loki uses nanoseconds
        start_time = end_time - (hours_back * 3600 * int(1e9))

        params = {
            "query": logql_query,
            "limit": limit,
            "start": start_time,
            "end": end_time,
            "direction": "backward" # Newest logs first
        }
        
        response = requests.get(self.query_endpoint, params=params)
        response.raise_for_status()
        
        data = response.json().get("data", {})
        results = data.get("result", [])
        
        # Flatten the log streams for easier LLM consumption
        parsed_logs = []
        for stream in results:
            labels = stream.get("stream", {})
            values = stream.get("values", [])
            for val in values:
                # val is [timestamp, log_line]
                parsed_logs.append({
                    "timestamp": val[0],
                    "labels": labels,
                    "message": val[1]
                })
                
        return parsed_logs