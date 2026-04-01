import requests
from typing import Dict, Any
from src.config.settings import settings

class PrometheusClient:
    """API wrapper for querying Prometheus metrics."""

    def __init__(self):
        self.base_url = settings.PROMETHEUS_URL
        self.query_endpoint = f"{self.base_url}/api/v1/query"

    def query(self, promql_query: str) -> Dict[str, Any]:
        """
        Execute an instant PromQL query.
        Example: query('up{job="node_exporter"}')
        """
        params = {"query": promql_query}
        response = requests.get(self.query_endpoint, params=params)
        response.raise_for_status()
        
        data = response.json().get("data", {})
        return data.get("result", [])

    def query_range(self, promql_query: str, start: str, end: str, step: str) -> Dict[str, Any]:
        """
        Execute a PromQL query over a range of time (useful for the Daily Digest).
        Timestamps should be RFC3339 or Unix timestamps.
        """
        endpoint = f"{self.base_url}/api/v1/query_range"
        params = {
            "query": promql_query,
            "start": start,
            "end": end,
            "step": step
        }
        response = requests.get(endpoint, params=params)
        response.raise_for_status()
        
        data = response.json().get("data", {})
        return data.get("result", [])