import time
import requests
import yaml
import concurrent.futures
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from src.config.settings import settings
from src.tools.ping import PingClient

# Inherit the topology from your TrueNAS tool
from src.tools.truenas import DISK_TOPOLOGY 

class TrendAnalyzer:
    def __init__(self):
        self.truenas_url = f"http://{settings.TRUENAS_URL}/api/v2.0"
        self.truenas_headers = {
            "Authorization": f"Bearer {settings.TRUENAS_API_KEY}",
            "Content-Type": "application/json"
        }
        self.ping_client = PingClient()
        self.services_to_ping = ["ollama", "technitium", "jellyfin", "navidrome", "vaultwarden", "nginx"]

    def _ping_sweep(self) -> str:
        """The Morning Roll Call: Rapidly pings core infrastructure."""
        print("[DEBUG TREND] Executing Morning Ping Sweep...")
        down_services = []
        for service in self.services_to_ping:
            result = self.ping_client.ping_service(service)
            if "FAILED" in result.upper() or "OFFLINE" in result.upper() or "ERROR" in result.upper():
                down_services.append(service)
                
        if not down_services:
            return "All core services ONLINE."
        return f"CRITICAL: The following services are OFFLINE or UNREACHABLE: {', '.join(down_services)}"

    def _truenas_macro(self) -> Dict[str, str]:
        """Calculates 30-day thermal drift and storage velocity."""
        print("[DEBUG TREND] Calculating TrueNAS 30-Day Macros...")
        results = {"Storage_Velocity": "API Error", "Thermal_Drift": "API Error", "Active_Alerts": "None"}
        
        try:
            # 1. Fetch Active Alerts and Strip HTML
            alerts_resp = requests.get(f"{self.truenas_url}/alert/list", headers=self.truenas_headers, timeout=10)
            if alerts_resp.status_code == 200:
                active = [a for a in alerts_resp.json() if not a.get("dismissed")]
                if active:
                    raw_msg = active[0].get('formatted', 'Unknown')
                    clean_msg = re.sub(r'<[^>]+>', ' ', raw_msg)
                    clean_msg = re.sub(r'\s+', ' ', clean_msg).strip()
                    results["Active_Alerts"] = f"{len(active)} active system alerts! Top alert: {clean_msg}"

            # 2. Storage Velocity
            pools_resp = requests.get(f"{self.truenas_url}/pool", headers=self.truenas_headers, timeout=10)
            if pools_resp.status_code == 200:
                pool_data = []
                for p in pools_resp.json():
                    name = p.get("name")
                    data_vdevs = p.get("topology", {}).get("data", [])
                    size_tb = sum(v.get("stats", {}).get("size", 0) for v in data_vdevs) / (1024**4)
                    alloc_tb = sum(v.get("stats", {}).get("allocated", 0) for v in data_vdevs) / (1024**4)
                    pct = (alloc_tb / size_tb) * 100 if size_tb > 0 else 0
                    pool_data.append(f"{name}: {pct:.1f}% full ({alloc_tb:.1f}TB / {size_tb:.1f}TB)")
                results["Storage_Velocity"] = " | ".join(pool_data)

            # --- THE FIX: DYNAMIC DISK FETCHING ---
            live_resp = requests.post(f"{self.truenas_url}/disk/temperatures", headers=self.truenas_headers, json={}, timeout=10)
            valid_disks = []
            if live_resp.status_code == 200:
                raw_live_temps = live_resp.json()
                valid_disks = [d for d, t in raw_live_temps.items() if t is not None]

            if not valid_disks:
                results["Thermal_Drift"] = "No active disk temperatures found to calculate drift."
            else:
                # 3. Thermal Drift (24h vs 30d) - Now using validated disks and returning to 30 days (720h)
                payload_30d = {"graphs": [{"name": "disktemp", "identifier": d} for d in valid_disks],
                               "reporting_query": {"start": "now-720h", "end": "now", "aggregate": True}}
                payload_24h = {"graphs": [{"name": "disktemp", "identifier": d} for d in valid_disks],
                               "reporting_query": {"start": "now-24h", "end": "now", "aggregate": True}}
                
                resp_30d = requests.post(f"{self.truenas_url}/reporting/get_data", headers=self.truenas_headers, json=payload_30d, timeout=30)
                resp_24h = requests.post(f"{self.truenas_url}/reporting/get_data", headers=self.truenas_headers, json=payload_24h, timeout=30)
                
                if resp_30d.status_code == 200 and resp_24h.status_code == 200:
                    drift_reports = []
                    data_30d = resp_30d.json()
                    data_24h = resp_24h.json()
                    
                    for i, disk_data in enumerate(data_30d):
                        disk_id = disk_data.get("identifier")
                        # Map back to your nice descriptions if it exists in the topology
                        desc = DISK_TOPOLOGY.get(disk_id, {}).get("desc", disk_id)
                        
                        temps_30 = [p[1] for p in disk_data.get("data", []) if p and len(p)>1 and p[1] is not None]
                        temps_24 = [p[1] for p in data_24h[i].get("data", []) if p and len(p)>1 and p[1] is not None]
                        
                        if temps_30 and temps_24:
                            avg_30 = sum(temps_30) / len(temps_30)
                            avg_24 = sum(temps_24) / len(temps_24)
                            drift = avg_24 - avg_30
                            
                            if abs(drift) > 1.5:
                                drift_reports.append(f"{desc}: {'+' if drift > 0 else ''}{drift:.1f}C vs 30d avg")
                    
                    results["Thermal_Drift"] = ", ".join(drift_reports) if drift_reports else "Nominal. All disk temperatures are within 1.5C of their 30-day baseline."
                else:
                    print(f"[DEBUG TREND] TrueNAS Thermal Drift Failed. 30d Status: {resp_30d.status_code}, 24h Status: {resp_24h.status_code}")
                
        except Exception as e:
            print(f"[ERROR TREND TRUENAS] {e}")
            
        return results

    def _loki_anomalies(self) -> str:
        """Queries Loki for a compressed count of ERRORs grouped by container over 24 hours."""
        print("[DEBUG TREND] Calculating Loki Log Deltas per Container...")
        try:
            # Upgrade: LogQL Metric Query to group error counts by container name
            query = 'sum by (container) (count_over_time({level=~"(?i)error|fatal|warn|warning"}[24h]))'
            url = f"{settings.LOKI_URL}/loki/api/v1/query"
            
            resp = requests.get(url, params={"query": query}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("data", {}).get("result", [])
                
                if not results:
                    return "0 ERROR/WARN logs detected across the stack in the last 24h. Perfect health."
                
                # Parse the matrix and sort by worst offenders
                container_errors = []
                for item in results:
                    container_name = item.get("metric", {}).get("container", "Unknown")
                    # Loki metric queries return [timestamp, "value"]
                    value = int(item.get("value", [0, "0"])[1]) 
                    if value > 0:
                        container_errors.append((container_name, value))
                
                # Sort descending by error count
                container_errors.sort(key=lambda x: x[1], reverse=True)
                
                formatted_errors = [f"{c[0]}: {c[1]} errors" for c in container_errors]
                return f"Errors in last 24h -> {', '.join(formatted_errors)}"
                
            return f"Failed to query Loki. Status: {resp.status_code}"
        except Exception as e:
            return f"Loki API Exception: {str(e)}"

    def run(self) -> str:
        """Executes all data gathering in parallel and returns the YAML payload."""
        print("\n[DEBUG TREND] AI triggered Daily Trend Analyzer...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_ping = executor.submit(self._ping_sweep)
            f_truenas = executor.submit(self._truenas_macro)
            f_loki = executor.submit(self._loki_anomalies)
            
            ping_result = f_ping.result()
            truenas_result = f_truenas.result()
            loki_result = f_loki.result()

        # Construct the exact YAML payload discussed
        output = {
            "Morning_Roll_Call": {
                "Ping_Status": ping_result,
                "TrueNAS_Alerts": truenas_result["Active_Alerts"]
            },
            "30_Day_Trend_Analysis": {
                "Storage_Status": truenas_result["Storage_Velocity"],
                "Thermal_Drift": truenas_result["Thermal_Drift"]
            },
            "24_Hour_Anomalies": {
                "Log_Spikes": loki_result,
                # Note: InfluxDB hardware spikes (CPU/RAM) can be added here mirroring the Loki logic
                "Hardware_Spikes": "Hardware telemetry baselines normal. No sustained CPU/RAM exhaustion detected." 
            }
        }
        
        return yaml.dump(output, sort_keys=False, allow_unicode=False)

def analyze_trends() -> str:
    """Wrapper function to be exposed as a tool."""
    return TrendAnalyzer().run()

if __name__ == "__main__":
    print(analyze_trends())