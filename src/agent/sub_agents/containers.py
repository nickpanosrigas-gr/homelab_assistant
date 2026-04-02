from langchain_core.tools import tool
from src.clients.prometheus import PrometheusClient
import logging

logger = logging.getLogger(__name__)

@tool
def get_container_status(app_name: str) -> str:
    """
    Checks if a specific docker container (like 'jellyfin', 'n8n', etc.) is running.
    Use this tool whenever the user asks if a service or app is up, working, or down.
    """
    logger.info(f"AI called tool: get_container_status for '{app_name}'")
    prom = PrometheusClient()
    
    # Simple PromQL query: Assumes you use cAdvisor or similar to track containers
    query = f'up{{container=~".*{app_name}.*"}}'
    
    try:
        results = prom.query(query)
        if not results:
            return f"Could not find any telemetry for container: {app_name}. It might be powered off or not monitored."
        
        state = results[0]['value'][1]
        if state == "1":
            return f"SUCCESS: Container {app_name} is UP and running normally."
        else:
            return f"ALERT: Container {app_name} is DOWN."
            
    except Exception as e:
        return f"Error querying Prometheus infrastructure: {e}"