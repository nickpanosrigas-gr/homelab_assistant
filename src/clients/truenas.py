import requests
import json
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
                size_tb = p.get("topology", {}).get("data", [{}])[0].get("stats", {}).get("size", 0) / (1024**4)
                alloc_tb = p.get("topology", {}).get("data", [{}])[0].get("stats", {}).get("allocated", 0) / (1024**4)
                summary.append({
                    "name": p.get("name"),
                    "status": p.get("status"),
                    "healthy": p.get("healthy"),
                    "capacity_tb": round(size_tb, 2),
                    "used_tb": round(alloc_tb, 2)
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

    def get_disk_temps(self) -> str:
        """Fetches live temperatures for all drives. This tool requires NO input parameters."""
        url = f"{self.base_url}/disk/temperatures"
        print(f"\n[DEBUG TRUENAS] Fetching Disk Temps via POST: {url} with empty payload")
        
        try:
            # TrueNAS requires a POST with an empty JSON body for this specific endpoint
            response = requests.post(url, headers=self.headers, json={}, timeout=10)
            
            if response.status_code != 200:
                print(f"[DEBUG TRUENAS] Raw Error Response: {response.text}")
                
            response.raise_for_status()
            temps = response.json()
            
            print(f"[DEBUG TRUENAS] Successfully fetched temperatures for {len(temps)} disk(s).")
            return json.dumps(temps, indent=2)
            
        except requests.exceptions.RequestException as e:
            print(f"[DEBUG TRUENAS] EXCEPTION CAUGHT: {str(e)}")
            return f"API Error (Temps): {str(e)}"

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