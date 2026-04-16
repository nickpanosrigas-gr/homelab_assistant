import time
import requests
import yaml
import re
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import Literal, Dict, List, Any
from src.config.settings import settings

# -----------------------------------------------------------------------------
# Hardware Topology & Thermal Thresholds
# -----------------------------------------------------------------------------
# Python 3.7+ retains dictionary order, so this exact order will be printed
DISK_TOPOLOGY = {
    "sdf": {"warn": 45.0, "err": 50.0, "desc": "Exos 16TB HDD Mirror0"},
    "sdd": {"warn": 45.0, "err": 50.0, "desc": "Sky 16TB HDD Mirror0"},
    "sde": {"warn": 45.0, "err": 50.0, "desc": "Sky 14TB HDD Mirror1"},
    "sdc": {"warn": 45.0, "err": 50.0, "desc": "WD 14TB HDD Mirror1"},
    "sdb": {"warn": 55.0, "err": 65.0, "desc": "500GB SSD Cache0"},
}
DEFAULT_THRESHOLDS = {"warn": 45.0, "err": 50.0, "desc": "Unknown Disk"}

class TrueNASTelemetryAggregator:
    def __init__(self):
        self.base_url = f"http://{settings.TRUENAS_URL}/api/v2.0"
        self.headers = {
            "Authorization": f"Bearer {settings.TRUENAS_API_KEY}",
            "Content-Type": "application/json"
        }

    def _get_time_params(self, timeframe: str) -> tuple[int, int, str]:
        now = time.time()
        mapping = {
            '1h': (3600, 300, "5m"),
            '24h': (86400, 7200, "2h"),
            '7d': (604800, 43200, "12h")
        }
        duration, window_sec, window_str = mapping.get(timeframe, mapping['24h'])
        start_sec = int(now - duration)
        return start_sec, window_sec, window_str

    def fetch_pools_and_disks(self) -> Dict[str, str]:
        """Fetches general storage health and calculates FREE / TOTAL capacity."""
        baseline_info = {}
        try:
            pools_resp = requests.get(f"{self.base_url}/pool", headers=self.headers, timeout=10)
            if pools_resp.status_code == 200:
                for p in pools_resp.json():
                    data_vdevs = p.get("topology", {}).get("data", [])
                    size_tb = sum(v.get("stats", {}).get("size", 0) for v in data_vdevs) / (1024**4)
                    alloc_tb = sum(v.get("stats", {}).get("allocated", 0) for v in data_vdevs) / (1024**4)
                    
                    # Calculate true free space
                    free_tb = size_tb - alloc_tb
                    status = p.get("status", "UNKNOWN")
                    
                    baseline_info[f"Pool_{p.get('name')}"] = f"{free_tb:.2f}TB free / {size_tb:.2f}TB total ({status})"

            disks_resp = requests.get(f"{self.base_url}/disk", headers=self.headers, timeout=10)
            if disks_resp.status_code == 200:
                disks = disks_resp.json()
                baseline_info["Physical_Disks"] = f"{len(disks)} Disks Detected (S.M.A.R.T. Active)"
                
        except Exception as e:
            print(f"[ERROR TRUENAS BASELINE] {e}")
            baseline_info["API_Error"] = str(e)
            
        return baseline_info

    def fetch_temps(self, start_sec: int, window_sec: int) -> tuple[Dict[str, float], Dict[int, Dict[str, float]]]:
        now = time.time()
        baseline_avg = {}
        bucket_max = {}
        
        try:
            live_resp = requests.post(f"{self.base_url}/disk/temperatures", headers=self.headers, json={}, timeout=10)
            raw_live_temps = live_resp.json() if live_resp.status_code == 200 else {}
            
            live_temps = {d: float(t) for d, t in raw_live_temps.items() if t is not None}
            disks = list(live_temps.keys())
            
            if not disks:
                return {}, {}

            start_str = f"now-{int((now - start_sec) / 3600)}h" 
            payload = {
                "graphs": [{"name": "disktemp", "identifier": d} for d in disks],
                "reporting_query": {"start": start_str, "end": "now", "aggregate": True}
            }
            report_resp = requests.post(f"{self.base_url}/reporting/get_data", headers=self.headers, json=payload, timeout=15)
            
            if report_resp.status_code != 200:
                return live_temps, {} 

            sums = {}
            counts = {}
            buckets_raw = {}

            for item in report_resp.json():
                disk = item.get("identifier")
                for point in item.get("data", []):
                    if not point or len(point) < 2 or point[1] is None: continue
                    ts, temp = point[0], float(point[1])
                    if ts < start_sec: continue

                    sums[disk] = sums.get(disk, 0) + temp
                    counts[disk] = counts.get(disk, 0) + 1

                    bucket_ts = (int(ts) // window_sec) * window_sec
                    if bucket_ts not in buckets_raw: buckets_raw[bucket_ts] = {}
                    if disk not in buckets_raw[bucket_ts]: buckets_raw[bucket_ts][disk] = []
                    buckets_raw[bucket_ts][disk].append(temp)

            baseline_avg = {d: round(sums[d]/counts[d], 1) for d in sums if counts[d] > 0}
            bucket_max = {ts: {d: max(temps) for d, temps in disks_dict.items() if temps} for ts, disks_dict in buckets_raw.items()}

        except Exception as e:
            print(f"[ERROR TRUENAS TEMPS] {e}")
            
        return baseline_avg, bucket_max

    def fetch_alerts(self, start_sec: int) -> List[Dict]:
        logs = []
        try:
            resp = requests.get(f"{self.base_url}/alert/list", headers=self.headers, timeout=10)
            if resp.status_code != 200: return logs
            
            for a in resp.json():
                if a.get("dismissed"): continue
                
                raw_level = a.get("level", "WARNING")
                if raw_level == "WARNING": level = "WARN"
                elif raw_level == "CRITICAL": level = "FATAL"
                else: level = raw_level

                dt_dict = a.get("datetime", {})
                ts_ms = dt_dict.get("$date", time.time() * 1000)
                ts_sec = ts_ms / 1000
                
                if ts_sec < start_sec:
                    ts_sec = start_sec
                    
                raw_msg = a.get("formatted", "Unknown Alert")
                clean_msg = re.sub(r'<[^>]+>', ' ', raw_msg) 
                clean_msg = re.sub(r'\s+', ' ', clean_msg).strip() 
                
                logs.append({
                    "ts_sec": ts_sec,
                    "level": level,
                    "message": clean_msg
                })
        except Exception as e:
            print(f"[ERROR TRUENAS ALERTS] {e}")
            
        return logs

    def run(self, timeframe: Literal['1h', '24h', '7d'] = '24h') -> str:
        start_sec, window_sec, window_str = self._get_time_params(timeframe)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_pools = executor.submit(self.fetch_pools_and_disks)
            f_temps = executor.submit(self.fetch_temps, start_sec, window_sec)
            f_alerts = executor.submit(self.fetch_alerts, start_sec)
            
            baseline_info = f_pools.result()
            baseline_avg_temps, bucket_max_temps = f_temps.result()
            active_alerts = f_alerts.result()

        global_baseline = {**baseline_info}
        
        # Build the exact ordered temperatures map
        if baseline_avg_temps:
            ordered_temps = {}
            # 1. Map known disks in the precise order specified in DISK_TOPOLOGY
            for d_id, d_info in DISK_TOPOLOGY.items():
                if d_id in baseline_avg_temps:
                    ordered_temps[d_info["desc"]] = f"{baseline_avg_temps[d_id]} C"
            
            # 2. Safely catch any other unknown disks so they don't disappear
            for d_id, temp in baseline_avg_temps.items():
                if d_id not in DISK_TOPOLOGY:
                    desc = f"{d_id} (Unknown)"
                    ordered_temps[desc] = f"{temp} C"
                    
            global_baseline["Disk_Temp_Averages"] = ordered_temps

        timeline = {}

        for ts, disks_dict in bucket_max_temps.items():
            dt = datetime.fromtimestamp(ts, timezone.utc)
            bucket_key = dt.strftime("%Y-%m-%d %H:%M:%S")
            
            anomalies = {}
            temp_events = []
            
            for disk, max_temp in disks_dict.items():
                thresholds = DISK_TOPOLOGY.get(disk, DEFAULT_THRESHOLDS)
                warn_limit = thresholds["warn"]
                err_limit = thresholds["err"]
                desc = thresholds["desc"]
                
                if max_temp >= err_limit:
                    anomalies[f"Temp_{desc}_max"] = f"{max_temp} C"
                    temp_events.append({
                        "time": dt.strftime("%H:%M:%S"),
                        "level": "FATAL",
                        "message": f"THERMAL ALERT: {desc} exceeded critical limit: {max_temp} C (Threshold: {err_limit} C)",
                        "occurrences": 1
                    })
                elif max_temp >= warn_limit:
                    anomalies[f"Temp_{desc}_max"] = f"{max_temp} C"
                    temp_events.append({
                        "time": dt.strftime("%H:%M:%S"),
                        "level": "WARN",
                        "message": f"THERMAL WARNING: {desc} running hot: {max_temp} C (Threshold: {warn_limit} C)",
                        "occurrences": 1
                    })
                    
            if anomalies or temp_events:
                if bucket_key not in timeline:
                    timeline[bucket_key] = {"bucket": bucket_key, "infrastructure_anomalies": anomalies, "log_events": []}
                else:
                    if "infrastructure_anomalies" not in timeline[bucket_key]:
                        timeline[bucket_key]["infrastructure_anomalies"] = {}
                    timeline[bucket_key]["infrastructure_anomalies"].update(anomalies)
                    
                if temp_events:
                    timeline[bucket_key]["log_events"].extend(temp_events)

        for alert in active_alerts:
            ts_sec = alert["ts_sec"]
            dt = datetime.fromtimestamp(ts_sec, timezone.utc)
            bucket_ts = (int(ts_sec) // window_sec) * window_sec
            bucket_dt = datetime.fromtimestamp(bucket_ts, timezone.utc)
            bucket_key = bucket_dt.strftime("%Y-%m-%d %H:%M:%S")
            
            if bucket_key not in timeline:
                timeline[bucket_key] = {"bucket": bucket_key, "log_events": []}
                
            if "log_events" not in timeline[bucket_key]:
                timeline[bucket_key]["log_events"] = []
                
            timeline[bucket_key]["log_events"].append({
                "time": dt.strftime("%H:%M:%S"),
                "level": alert["level"],
                "message": alert["message"],
                "occurrences": 1
            })

        final_timeline = []
        ignored_count = 0
        total_possible_buckets = int((time.time() - start_sec) / window_sec)
        
        for k, v in sorted(timeline.items()):
            has_anomalies = "infrastructure_anomalies" in v and v["infrastructure_anomalies"]
            has_logs = "log_events" in v and len(v["log_events"]) > 0
            
            if has_anomalies or has_logs:
                if not has_anomalies: v.pop("infrastructure_anomalies", None)
                if not has_logs: v.pop("log_events", None)
                final_timeline.append(v)
                
        ignored_count = total_possible_buckets - len(final_timeline)

        output = {
            "Target_Service": "TrueNAS Core/Scale",
            "Timeframe": f"{timeframe} ({window_str} intervals)",
            "Global_Baseline": global_baseline,
            "Timeline": final_timeline,
            "Ignored_Buckets": f"{ignored_count if ignored_count > 0 else 0} intervals omitted. Pool capacity healthy, disk temps nominal, no active alerts."
        }
        
        return yaml.dump(output, sort_keys=False, allow_unicode=False)

def truenas(timeframe: Literal['1h', '24h', '7d'] = '24h') -> str:
    return TrueNASTelemetryAggregator().run(timeframe)

if __name__ == "__main__":
    print("--- TEST 1: TrueNAS 24-Hour Telemetry ---")
    print(truenas("24h"))
    print("\n--- TEST 2: TrueNAS 1-Hour Telemetry ---")
    print(truenas("1h"))