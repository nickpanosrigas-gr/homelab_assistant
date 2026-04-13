import time
import requests
import json
from datetime import datetime, timezone
from typing import Literal
from src.config.settings import settings

class TrueNASClient:
    def __init__(self):
        self.base_url = f"http://{settings.TRUENAS_URL}/api/v2.0"
        self.headers = {
            "Authorization": f"Bearer {settings.TRUENAS_API_KEY}",
            "Content-Type": "application/json"
        }

    def get_pool_health(self) -> str:
        """Fetches ZFS pool health and capacity. This tool requires NO input parameters."""
        url = f"{self.base_url}/pool"
        print(f"\n[DEBUG TRUENAS] Fetching Pool Health via GET: {url}")
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code != 200:
                print(f"[DEBUG TRUENAS] Raw Error Response: {response.text}")
                
            response.raise_for_status()
            pools = response.json()
            
            # Extract only the essential data to save LLM tokens
            summary = []
            for p in pools:
                # Sum up stats across ALL data vdevs (fixes multi-vdev pools)
                data_vdevs = p.get("topology", {}).get("data", [])
                
                size_bytes = sum(vdev.get("stats", {}).get("size", 0) for vdev in data_vdevs)
                alloc_bytes = sum(vdev.get("stats", {}).get("allocated", 0) for vdev in data_vdevs)
                
                size_tb = size_bytes / (1024**4)
                alloc_tb = alloc_bytes / (1024**4)
                free_tb = size_tb - alloc_tb
                
                summary.append({
                    "name": p.get("name"),
                    "status": p.get("status"),
                    "healthy": p.get("healthy"),
                    "total_capacity_tb": round(size_tb, 2),
                    "used_tb": round(alloc_tb, 2),
                    "free_tb": round(free_tb, 2)
                })
            
            print(f"[DEBUG TRUENAS] Successfully fetched pool health for {len(summary)} pool(s).")
            return json.dumps(summary, indent=2)
            
        except requests.exceptions.RequestException as e:
            print(f"[DEBUG TRUENAS] EXCEPTION CAUGHT: {str(e)}")
            return f"API Error (Pools): {str(e)}"

    def get_disk_health(self) -> str:
        """Fetches S.M.A.R.T. status and physical disk info. This tool requires NO input parameters."""
        url = f"{self.base_url}/disk"
        print(f"\n[DEBUG TRUENAS] Fetching Disk Health via GET: {url}")
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code != 200:
                print(f"[DEBUG TRUENAS] Raw Error Response: {response.text}")
                
            response.raise_for_status()
            disks = response.json()
            
            summary = []
            for d in disks:
                summary.append({
                    "name": d.get("name"),
                    "model": d.get("model"),
                    "serial": d.get("serial"),
                    "size_gb": round(d.get("size", 0) / (1024**3), 2),
                    "rotation_rate": d.get("rotationrate"),
                    "toggles": d.get("toggles")
                })
                
            print(f"[DEBUG TRUENAS] Successfully fetched disk health for {len(summary)} disk(s).")
            return json.dumps(summary, indent=2)
            
        except requests.exceptions.RequestException as e:
            print(f"[DEBUG TRUENAS] EXCEPTION CAUGHT: {str(e)}")
            return f"API Error (Disks): {str(e)}"

    def get_disk_temps(self, timeframe: Literal['day', 'week', 'month'] = 'day') -> str:
        """
        Fetches live temps and formats historical temperatures into structured Trends and Extremes.
        """
        live_url = f"{self.base_url}/disk/temperatures"
        print(f"\n[DEBUG TRUENAS] Fetching Live Disk Temps...")
        
        try:
            live_resp = requests.post(live_url, headers=self.headers, json={}, timeout=10)
            live_resp.raise_for_status()
            live_temps = live_resp.json() # {"sda": 35, "sdb": 36}
            
            disks = sorted(list(live_temps.keys()))
            if not disks:
                return "No temperature data available for any disks."

            # 1. Define the Splits (in seconds)
            now = time.time()
            if timeframe == 'day':
                start_sec = now - (24 * 3600)
                avg_window = 2 * 3600    # 2h split
                max_window = 8 * 3600    # 8h split
            elif timeframe == 'week':
                start_sec = now - (7 * 24 * 3600)
                avg_window = 12 * 3600   # 12h split
                max_window = 24 * 3600   # 24h split
            elif timeframe == 'month':
                start_sec = now - (30 * 24 * 3600)
                avg_window = 72 * 3600   # 72h split
                max_window = 168 * 3600  # 168h split
            else:
                return "Error: timeframe must be 'day', 'week', or 'month'."

            # 2. Fetch Historical Temperatures via Reporting API
            reporting_url = f"{self.base_url}/reporting/get_data"
            graphs = [{"name": "disktemp", "identifier": disk} for disk in disks]
            
            # Start string formatting for TrueNAS API
            start_str = f"now-{int((now - start_sec) / 3600)}h" 
            
            payload = {
                "graphs": graphs,
                "reporting_query": {
                    "start": start_str,
                    "end": "now",
                    "aggregate": True # Tells TrueNAS to not return millions of raw points
                }
            }

            print(f"[DEBUG TRUENAS] Fetching Historical Temps (Start: {start_str})...")
            report_resp = requests.post(reporting_url, headers=self.headers, json=payload, timeout=15)
            
            if report_resp.status_code != 200:
                print(f"[DEBUG TRUENAS] Reporting API failed. Returning only live temps.")
                live_strs = [f"{k}: {v}°C" for k, v in live_temps.items()]
                return "Historical Data Unavailable. Live Temps: " + ", ".join(live_strs)

            report_data = report_resp.json()

            # 3. Process and Bin the Data into Windows
            trends_data = {}   # { timestamp: { "sda": [val1, val2], "sdb": [...] } }
            extremes_data = {} # { timestamp: { "sda": [val1, val2], "sdb": [...] } }

            for item in report_data:
                disk_name = item.get("identifier")
                for point in item.get("data", []):
                    if not point or len(point) < 2 or point[1] is None:
                        continue
                    
                    ts = point[0]
                    temp = point[1]
                    
                    if ts < start_sec:
                        continue
                        
                    # Calculate the "bucket" this timestamp belongs to
                    trend_bin = (ts // avg_window) * avg_window
                    extreme_bin = (ts // max_window) * max_window
                    
                    # Store for Trend averages
                    if trend_bin not in trends_data: trends_data[trend_bin] = {}
                    if disk_name not in trends_data[trend_bin]: trends_data[trend_bin][disk_name] = []
                    trends_data[trend_bin][disk_name].append(temp)
                    
                    # Store for Extreme maxes
                    if extreme_bin not in extremes_data: extremes_data[extreme_bin] = {}
                    if disk_name not in extremes_data[extreme_bin]: extremes_data[extreme_bin][disk_name] = []
                    extremes_data[extreme_bin][disk_name].append(temp)

            # 4. Helper Function to generate the clean CSV
            def build_csv(data_dict, is_max=False):
                if not data_dict:
                    return "No data points found."
                    
                lines = []
                header = ["_time"] + disks
                lines.append(",".join(header))
                
                # Sort chronologically
                for ts in sorted(data_dict.keys()):
                    time_str = datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
                    row = [time_str]
                    for disk in disks:
                        vals = data_dict[ts].get(disk, [])
                        if vals:
                            # Calculate Average or Max
                            val = max(vals) if is_max else sum(vals) / len(vals)
                            row.append(f"{val:.1f}")
                        else:
                            row.append("") # Empty column if disk was offline/missing
                    lines.append(",".join(row))
                return "\n".join(lines)

            # 5. Format the Final LLM Payload
            averages_csv = build_csv(trends_data, is_max=False)
            extremes_csv = build_csv(extremes_data, is_max=True)
            
            live_strs = [f"{k}: {v}°C" for k, v in live_temps.items()]
            
            llm_payload = (
                f"LIVE TEMPERATURES (Right Now):\n{', '.join(live_strs)}\n\n"
                f"EXTREMES (Max values over {int(max_window/3600)}h windows):\n"
                "Note: Check this to ensure no disk exceeded safe operating temperatures.\n"
                f"```csv\n{extremes_csv}\n```\n\n"
                f"TRENDS (Averages over {int(avg_window/3600)}h windows):\n"
                "Note: Use this to understand normal heating/cooling patterns.\n"
                f"```csv\n{averages_csv}\n```"
            )
            
            print(f"[DEBUG TRUENAS] Processed {len(trends_data)} trend windows and {len(extremes_data)} extreme windows.")
            return llm_payload
            
        except requests.exceptions.RequestException as e:
            error_msg = f"API Error (Temps): {str(e)}"
            print(f"[DEBUG TRUENAS] EXCEPTION CAUGHT: {error_msg}")
            return error_msg

    def get_alerts(self) -> str:
        """Fetches active system alerts. This tool requires NO input parameters."""
        url = f"{self.base_url}/alert/list"
        print(f"\n[DEBUG TRUENAS] Fetching Active Alerts via GET: {url}")
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code != 200:
                print(f"[DEBUG TRUENAS] Raw Error Response: {response.text}")
                
            response.raise_for_status()
            alerts = response.json()
            
            # Filter out dismissed alerts
            active = [a for a in alerts if not a.get("dismissed")]
            print(f"[DEBUG TRUENAS] Successfully fetched {len(active)} active alert(s).")
            
            if not active:
                return "No active alerts. System is healthy."
                
            summary = [{"level": a.get("level"), "message": a.get("formatted")} for a in active]
            return json.dumps(summary, indent=2)
            
        except requests.exceptions.RequestException as e:
            print(f"[DEBUG TRUENAS] EXCEPTION CAUGHT: {str(e)}")
            return f"API Error (Alerts): {str(e)}"