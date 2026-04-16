from langchain_core.tools import tool
from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient
from src.clients.truenas import TrueNASClient

# Initialize your clients once
influx = InfluxDBClient()
loki = LokiClient()
truenas = TrueNASClient()

@tool
def query_influx_metrics(service_name: str, timeframe: str = "24h") -> dict:
    """
    Fetches hardware metrics (CPU, RAM, Disk, Network) for a specific Docker service.
    Valid service_names: jellyfin, navidrome, nginx-proxy-manager, vaultwarden, etc.
    """
    # Note: Assuming your InfluxDBClient has a method like this
    return influx.get_container_metrics(service_name, timeframe)

@tool
def query_loki_logs(service_name: str, limit: int = 50) -> str:
    """
    Fetches the most recent system or error logs for a specific service.
    Use this to troubleshoot why a service like jellyfin or vaultwarden is failing.
    """
    # Note: Assuming your LokiClient has a method like this
    return loki.get_logs(service_name, limit)

@tool
def query_truenas_health(timeframe: str = 'day') -> dict:
    """
    Fetches full TrueNAS storage telemetry including ZFS pool health, 
    SMART disk data, disk temperatures, and active alerts.
    """
    return {
        "pool_health": truenas.get_pool_health(),
        "disk_health": truenas.get_disk_health(),
        "disk_temps": truenas.get_disk_temps(timeframe=timeframe),
        "alerts": truenas.get_alerts()
    }