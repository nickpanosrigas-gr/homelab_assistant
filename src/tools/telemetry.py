import re
import yaml
import requests
import concurrent.futures
from typing import Literal, Dict, List, Any
from datetime import datetime, timezone, timedelta
from src.config.settings import settings

# -----------------------------------------------------------------------------
# Configuration: Define which services live where
# -----------------------------------------------------------------------------
PROXMOX_LXC_SERVICES = ['jellyfin', 'technitium', 'ollama']
DOCKER_SERVICES = ['navidrome', 'vaultwarden', 'wireguard', 'nginx']

def mask_dynamic_data(log_message: str) -> str:
    """Masks IPs, UUIDs, and timestamps to improve LLM deduplication."""
    msg = re.sub(r'\b\d{1,3}(?:\.\d{1,3}){3}\b', '<IP>', log_message)
    msg = re.sub(r'\b[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b', '<UUID>', msg)
    msg = re.sub(r'\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?', '<TIME>', msg)
    return msg.strip()

class FusedTelemetryAggregator:
    def __init__(self):
        self.influx_url = f"{settings.INFLUXDB_URL}/api/v2/query?org={settings.INFLUXDB_ORG}"
        self.influx_headers = {
            "Authorization": f"Token {settings.INFLUXDB_TOKEN}",
            "Accept": "application/csv", 
            "Content-Type": "application/vnd.flux"
        }
        self.loki_url = f"{settings.LOKI_URL}/loki/api/v1/query_range"

    def _get_time_params(self, timeframe: str) -> tuple[str, str, int, int]:
        now = datetime.now(timezone.utc)
        mapping = {
            '1h': ("-1h", "5m", timedelta(hours=1)),
            '7d': ("-7d", "12h", timedelta(days=7)),
            '24h': ("-24h", "2h", timedelta(days=1))
        }
        start_flux, window, delta = mapping.get(timeframe, mapping['24h'])
        start_ns = int((now - delta).timestamp() * 1_000_000_000)
        end_ns = int(now.timestamp() * 1_000_000_000)
        return start_flux, window, start_ns, end_ns

    def fetch_influx_metrics(self, service_name: str, start: str, window: str) -> Dict[str, Any]:
        """Dynamically routes query to Docker or Proxmox buckets and grabs Avg/Max baselines."""
        is_proxmox = service_name.lower() in PROXMOX_LXC_SERVICES
        
        print(f"[DEBUG TELEMETRY] Executing InfluxDB Flux query for {service_name} (is_proxmox={is_proxmox})")

        if is_proxmox:
            flux_query = f"""
            data = from(bucket: "{settings.INFLUXDB_PROXMOX_BUCKET}") 
              |> range(start: {start}) 
              |> filter(fn: (r) => r["_measurement"] == "system" and r["object"] == "lxc") 
              |> filter(fn: (r) => r["host"] =~ /(?i){service_name}/) 
              |> filter(fn: (r) => r["_field"] == "cpu" or r["_field"] == "mem")
              
            baseline_avg = data |> mean() |> yield(name: "baseline_avg")
            baseline_max = data |> max() |> yield(name: "baseline_max")
            buckets = data |> aggregateWindow(every: {window}, fn: max, createEmpty: true) |> yield(name: "buckets")
            """
        else:
            flux_query = f"""
            data = from(bucket: "{settings.INFLUXDB_DOCKER_BUCKET}") 
              |> range(start: {start}) 
              |> filter(fn: (r) => r["container_name"] =~ /(?i){service_name}/) 
              |> filter(fn: (r) => r["_field"] == "usage_percent" or r["_field"] == "usage")

            baseline_avg = data |> mean() |> yield(name: "baseline_avg")
            baseline_max = data |> max() |> yield(name: "baseline_max")
            buckets = data |> aggregateWindow(every: {window}, fn: max, createEmpty: true) |> yield(name: "buckets")
            """

        # Update dictionary to hold both avg and max baselines
        metrics = {"baseline_avg": {}, "baseline_max": {}, "buckets": {}}
        try:
            response = requests.post(self.influx_url, headers=self.influx_headers, data=flux_query, timeout=15)
            response.raise_for_status()
            
            lines = response.text.splitlines()
            header_map = {}
            
            for line in lines:
                parts = line.split(",")
                if not parts or len(parts) < 2: continue

                if "_field" in parts and "_value" in parts:
                    header_map = {name: i for i, name in enumerate(parts)}
                    continue
                
                if line.startswith("#") or "_time" in line or not header_map:
                    continue
                
                try:
                    res_type = parts[header_map["result"]]
                    raw_field = parts[header_map["_field"]]
                    val_str = parts[header_map["_value"]]
                    val = float(val_str) if val_str else 0.0
                    
                    if raw_field in ["usage_percent", "cpu"]:
                        standard_field = "cpu"
                    elif raw_field in ["usage", "mem"]:
                        standard_field = "ram"
                    else:
                        continue
                    
                    # Store data based on which query block it came from
                    if res_type == "baseline_avg":
                        metrics["baseline_avg"][standard_field] = val
                    elif res_type == "baseline_max":
                        metrics["baseline_max"][standard_field] = val
                    elif res_type == "buckets":
                        ts = parts[header_map["_time"]]
                        if ts not in metrics["buckets"]:
                            metrics["buckets"][ts] = {}
                        metrics["buckets"][ts][standard_field] = val
                except (KeyError, ValueError, IndexError):
                    continue
            
            print(f"[DEBUG TELEMETRY] Successfully parsed InfluxDB metrics for {service_name}")
            return metrics
        except Exception as e:
            print(f"[ERROR INFLUXDB] {e}")
            return metrics

    def fetch_loki_logs(self, service_name: str, start_ns: int, end_ns: int) -> List[tuple]:
        """Builds custom LogQL queries based on the service architecture."""
        lower_service = service_name.lower()
        
        print(f"[DEBUG TELEMETRY] Executing Loki LogQL query for {service_name}")
        
        # This one block now perfectly handles Jellyfin, Technitium, and Ollama
        if lower_service in PROXMOX_LXC_SERVICES:
            query = f'{{service_name=~"(?i){lower_service}-app|{lower_service}-sys"}} |~ "(?i){lower_service}" |~ "(?i)error|warn|fatal"'
        else:
            query = f'{{service_name=~"(?i){lower_service}"}} |~ "(?i)error|warn|fatal"'
            
        params = {"query": query, "limit": 1000, "start": str(start_ns), "end": str(end_ns), "direction": "forward"}
        
        try:
            response = requests.get(self.loki_url, params=params, timeout=10)
            response.raise_for_status()
            results = response.json().get("data", {}).get("result", [])
            
            logs = []
            for stream in results:
                # This loop is what grabs the logs from BOTH the -app and -sys streams
                for val in stream.get("values", []):
                    logs.append((int(val[0]) / 1_000_000_000, val[1].strip()))
            
            print(f"[DEBUG TELEMETRY] Successfully retrieved {len(logs)} log entries from Loki for {service_name}")
            
            # This sorts the fused logs chronologically before sending them to the AI
            return sorted(logs, key=lambda x: x[0])
        except Exception as e:
            print(f"[ERROR LOKI] {e}")
            return []

    def run(self, service_name: str, timeframe: Literal['1h', '24h', '7d'] = '24h') -> str:
        print(f"\n[DEBUG TELEMETRY] AI requested telemetry for service: '{service_name}' (Timeframe: {timeframe})")
        start_flux, window_flux, start_ns, end_ns = self._get_time_params(timeframe)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_influx = executor.submit(self.fetch_influx_metrics, service_name, start_flux, window_flux)
            future_loki = executor.submit(self.fetch_loki_logs, service_name, start_ns, end_ns)
            influx_data, raw_logs = future_influx.result(), future_loki.result()

        print(f"[DEBUG TELEMETRY] Fusing and processing infrastructure metrics and log anomalies...")

        # Extract both Averages and Maximums
        baseline_cpu_avg = influx_data["baseline_avg"].get("cpu", 0.0)
        baseline_ram_avg = influx_data["baseline_avg"].get("ram", 0.0)
        baseline_cpu_max = influx_data["baseline_max"].get("cpu", 0.0)
        baseline_ram_max = influx_data["baseline_max"].get("ram", 0.0)
        
        timeline = {}

        # Metric anomaly logic (Still using the average for anomaly thresholds)
        for ts, fields in influx_data["buckets"].items():
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            bucket_key = dt.strftime("%Y-%m-%d %H:%M:%S")
            cpu, ram = fields.get("cpu", 0.0), fields.get("ram", 0.0)
            
            anomalies = {}
            # Anomaly is defined as 30% above the average
            if cpu > (baseline_cpu_avg * 1.3) and cpu > 5.0:
                anomalies["CPU_max"] = f"{cpu:.2f}%"
            if ram > (baseline_ram_avg * 1.3) and ram > 0:
                anomalies["RAM_max"] = f"{ram / (1024*1024):.2f} MB"
                
            if anomalies:
                timeline[bucket_key] = {"bucket": bucket_key, "infrastructure_anomalies": anomalies, "log_events": []}

        # Log integration logic
        for ts_sec, text in raw_logs:
            dt = datetime.fromtimestamp(ts_sec, timezone.utc)
            bucket_key = dt.strftime("%Y-%m-%d %H:00:00") 
            
            if bucket_key not in timeline:
                timeline[bucket_key] = {"bucket": bucket_key, "log_events": []}
            
            msg = mask_dynamic_data(text)
            existing = next((l for l in timeline[bucket_key]["log_events"] if l["message"] == msg), None)
            if existing:
                existing["occurrences"] += 1
            else:
                timeline[bucket_key]["log_events"].append({
                    "time": dt.strftime("%H:%M:%S"),
                    "level": "ERROR" if "ERROR" in text.upper() else "WARN",
                    "message": msg,
                    "occurrences": 1
                })

        final_timeline = [v for k, v in sorted(timeline.items()) if v.get("infrastructure_anomalies") or v.get("log_events")]
        
        print(f"[DEBUG TELEMETRY] Telemetry compilation complete for {service_name}. Formatted {len(final_timeline)} buckets with events.")
        
        output = {
            "Target_Service": service_name,
            "Timeframe": f"{timeframe} ({window_flux} intervals)",
            "Global_Baseline": {
                "CPU_avg": f"{baseline_cpu_avg:.2f}%", 
                "CPU_max": f"{baseline_cpu_max:.2f}%", 
                "RAM_avg": f"{baseline_ram_avg/(1024*1024):.2f} MB",
                "RAM_max": f"{baseline_ram_max/(1024*1024):.2f} MB"
            },
            "Timeline": final_timeline,
            "Ignored_Buckets": f"{len(influx_data['buckets']) - len(final_timeline)} intervals omitted (Normal behavior)."
        }
        return yaml.dump(output, sort_keys=False)

def telemetry(service_name: str, timeframe: Literal['1h', '24h', '7d'] = '24h') -> str:
    return FusedTelemetryAggregator().run(service_name, timeframe)

if __name__ == "__main__":
    print(telemetry("navidrome","7d"))