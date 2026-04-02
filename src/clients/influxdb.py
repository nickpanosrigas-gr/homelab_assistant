import requests
from src.config.settings import settings

class InfluxDBClient:
    def __init__(self):
        # We append ?org= to the URL as done in the n8n POST request
        self.url = f"{settings.INFLUXDB_URL}/api/v2/query?org={settings.INFLUXDB_ORG}"
        self.headers = {
            "Authorization": f"Token {settings.INFLUXDB_TOKEN}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux"
        }

    def get_container_metrics(self, service_name: str) -> str:
        """
        Use this tool to fetch the last 24 hours of CPU, RAM, Disk, and Network metrics for Docker containers.
        
        ALLOWED INPUTS: jellyfin, technitiumdns, ollama, vaultwarden, wireguard, navidrome-navidrome-1, 
        nginx-proxy-manager, cloudflared, cloudflare-ddns, byparr, deunhealth, gluetun, jellyseerr, 
        profilarr, prowlarr, qbittorrent, radarr, sonarr, n8n, n8n-postgres, grafana, prometheus, 
        loki, promtail, telegraf, influxdb, open-webui.
        """
        
        # Injecting your exact n8n Flux query structure
        flux_query = f"""
        service_name = "{service_name}"
        
        from(bucket: "{settings.INFLUXDB_DOCKER_BUCKET}") 
          |> range(start: -7d) 
          |> filter(fn: (r) => r["container_name"] == service_name) 
          |> filter(fn: (r) => r["_field"] == "usage_percent" or r["_field"] == "usage" or r["_field"] == "io_service_bytes_recursive_read" or r["_field"] == "io_service_bytes_recursive_write" or r["_field"] == "rx_bytes" or r["_field"] == "tx_bytes") 
          |> keep(columns: ["_time", "_value", "_field", "_measurement", "container_name", "device", "network"]) 
          |> aggregateWindow(every: 1d, fn: mean, createEmpty: false) 
          |> yield(name: "docker_metrics")
        
        from(bucket: "{settings.INFLUXDB_PROXMOX_BUCKET}") 
          |> range(start: -24h) 
          |> filter(fn: (r) => r["_measurement"] == "system" and r["object"] == "lxc") 
          |> filter(fn: (r) => r["host"] == service_name) 
          |> filter(fn: (r) => r["_field"] == "cpu" or r["_field"] == "mem" or r["_field"] == "disk" or r["_field"] == "diskread" or r["_field"] == "diskwrite" or r["_field"] == "netin" or r["_field"] == "netout") 
          |> aggregateWindow(every: 2h, fn: mean, createEmpty: false) 
          |> keep(columns: ["_time", "_value", "_field", "host"]) 
          |> yield(name: "lxc_metrics")
        """

        try:
            response = requests.post(self.url, headers=self.headers, data=flux_query, timeout=15)
            response.raise_for_status()
            return response.text # Returns the CSV data from InfluxDB
        except requests.exceptions.RequestException as e:
            return f"Error fetching metrics for {service_name}: {str(e)}"