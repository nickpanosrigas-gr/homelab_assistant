import requests
from typing import Literal
from src.config.settings import settings

class InfluxDBClient:
    def __init__(self):
        self.url = f"{settings.INFLUXDB_URL}/api/v2/query?org={settings.INFLUXDB_ORG}"
        self.headers = {
            "Authorization": f"Token {settings.INFLUXDB_TOKEN}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux"
        }

    def get_container_metrics(self, service_name: str, timeframe: Literal['day', 'week', 'month'] = 'day') -> str:
        """
        Use this tool to fetch CPU, RAM, and Network metrics for Docker/LXC containers.
        It returns both 'Trends' (averages) and 'Extremes' (maximums) to help spot anomalies.
        
        Args:
            service_name: The name of the service (e.g., jellyfin, n8n-postgres).
            timeframe: The time period to query. Allowed values: 'day', 'week', 'month'.
        """
        print(f"\n[DEBUG INFLUXDB] AI requested metrics for: {service_name} | Timeframe: {timeframe}")
        
        # Define the time splits based on the chosen timeframe
        if timeframe == 'day':
            start_time = "-24h"
            avg_window = "2h"
            max_window = "8h"
        elif timeframe == 'week':
            start_time = "-7d"
            avg_window = "12h"
            max_window = "24h"
        elif timeframe == 'month':
            start_time = "-30d"
            avg_window = "72h"
            max_window = "168h"
        else:
            print(f"[DEBUG INFLUXDB] Error: Invalid timeframe '{timeframe}' provided by AI.")
            return "Error: timeframe must be 'day', 'week', or 'month'."

        print(f"[DEBUG INFLUXDB] Configured Windows -> Start: {start_time}, Averages: {avg_window}, Extremes: {max_window}")

        # We query both Averages (Trends) and Maximums (Extremes) simultaneously
        flux_query = f"""
        service_name = "{service_name}"
        
        // --- DOCKER AVERAGES ---
        from(bucket: "{settings.INFLUXDB_DOCKER_BUCKET}") 
          |> range(start: {start_time}) 
          |> filter(fn: (r) => r["container_name"] == service_name) 
          |> filter(fn: (r) => r["_field"] =~ /usage_percent|usage|rx_bytes|tx_bytes/) 
          |> aggregateWindow(every: {avg_window}, fn: mean, createEmpty: false) 
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "container_name", "usage_percent", "usage", "rx_bytes", "tx_bytes"])
          |> yield(name: "docker_averages")

        // --- DOCKER EXTREMES (MAX) ---
        from(bucket: "{settings.INFLUXDB_DOCKER_BUCKET}") 
          |> range(start: {start_time}) 
          |> filter(fn: (r) => r["container_name"] == service_name) 
          |> filter(fn: (r) => r["_field"] =~ /usage_percent|usage|rx_bytes|tx_bytes/) 
          |> aggregateWindow(every: {max_window}, fn: max, createEmpty: false) 
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "container_name", "usage_percent", "usage", "rx_bytes", "tx_bytes"])
          |> yield(name: "docker_extremes")
        
        // --- LXC AVERAGES ---
        from(bucket: "{settings.INFLUXDB_PROXMOX_BUCKET}") 
          |> range(start: {start_time}) 
          |> filter(fn: (r) => r["_measurement"] == "system" and r["object"] == "lxc") 
          |> filter(fn: (r) => r["host"] == service_name) 
          |> filter(fn: (r) => r["_field"] =~ /cpu|mem|netin|netout/) 
          |> aggregateWindow(every: {avg_window}, fn: mean, createEmpty: false) 
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "host", "cpu", "mem", "netin", "netout"])
          |> yield(name: "lxc_averages")

        // --- LXC EXTREMES (MAX) ---
        from(bucket: "{settings.INFLUXDB_PROXMOX_BUCKET}") 
          |> range(start: {start_time}) 
          |> filter(fn: (r) => r["_measurement"] == "system" and r["object"] == "lxc") 
          |> filter(fn: (r) => r["host"] == service_name) 
          |> filter(fn: (r) => r["_field"] =~ /cpu|mem|netin|netout/) 
          |> aggregateWindow(every: {max_window}, fn: max, createEmpty: false) 
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> keep(columns: ["_time", "host", "cpu", "mem", "netin", "netout"])
          |> yield(name: "lxc_extremes")
        """

        try:
            print(f"[DEBUG INFLUXDB] Executing Flux query at {self.url}...")
            response = requests.post(self.url, headers=self.headers, data=flux_query, timeout=15)
            response.raise_for_status()
            
            # ---------------------------------------------------------
            # PARSING AND CLEANING THE CSV FOR THE LLM
            # ---------------------------------------------------------
            raw_csv = response.text
            averages_lines = []
            extremes_lines = []
            
            for line in raw_csv.splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                
                parts = line.split(",")
                if len(parts) > 3:
                    result_name = parts[1] 
                    clean_line = ",".join(parts[3:]) 
                    
                    if "averages" in result_name:
                        if clean_line.startswith("_time") and len(averages_lines) > 0:
                            continue
                        averages_lines.append(clean_line)
                        
                    elif "extremes" in result_name:
                        if clean_line.startswith("_time") and len(extremes_lines) > 0:
                            continue
                        extremes_lines.append(clean_line)
                            
            if not averages_lines and not extremes_lines:
                print(f"[DEBUG INFLUXDB] Result: No data found for {service_name}.")
                return f"No metric data found for {service_name} in the last {timeframe}."

            averages_csv = "\n".join(averages_lines)
            extremes_csv = "\n".join(extremes_lines)

            llm_payload = (
                f"METRICS REPORT: {service_name}\n"
                f"Timeframe: Last {timeframe.capitalize()}\n\n"
                f"EXTREMES (Max values over {max_window} windows):\n"
                "Note: Use this to check for severe spikes or leaks.\n"
                f"```csv\n{extremes_csv}\n```\n\n"
                f"TRENDS (Averages over {avg_window} windows):\n"
                "Note: Use this to understand normal operating rhythm and baselines.\n"
                f"```csv\n{averages_csv}\n```"
            )
            
            print(f"[DEBUG INFLUXDB] Successfully parsed {len(averages_lines)-1} average rows and {len(extremes_lines)-1} extreme rows.")
            return llm_payload

        except requests.exceptions.RequestException as e:
            error_msg = f"Error fetching metrics for {service_name}: {str(e)}"
            print(f"[DEBUG INFLUXDB] EXCEPTION CAUGHT: {error_msg}")
            return error_msg