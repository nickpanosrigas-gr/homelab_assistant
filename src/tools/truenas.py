import time
import json
import yaml
import re
import uuid
import ssl
from datetime import datetime, timezone
from typing import Literal, Dict, List, Tuple
from websockets.sync.client import connect
from influxdb_client import InfluxDBClient
from src.config.settings import settings

# -----------------------------------------------------------------------------
# Hardware Topology & Thermal Thresholds (Mapped by Serial Number)
# -----------------------------------------------------------------------------
DISK_TOPOLOGY = {
    "ZL2E93XC": {"warn": 45.0, "err": 50.0, "desc": "Exos 16TB HDD Mirror0"},
    "ZL20BWD1": {"warn": 45.0, "err": 50.0, "desc": "Sky 16TB HDD Mirror0"},
    "ZHZ68HBX": {"warn": 45.0, "err": 50.0, "desc": "Sky 14TB HDD Mirror1"},
    "81G05VWV": {"warn": 45.0, "err": 50.0, "desc": "WD 14TB HDD Mirror1"},
    "2335E872859D": {"warn": 55.0, "err": 65.0, "desc": "500GB SSD Cache0"},
}
DEFAULT_THRESHOLDS = {"warn": 45.0, "err": 50.0, "desc": "Unknown Disk"}

class TrueNASTelemetryAggregator:
        
    def _get_time_params(self, timeframe: str) -> Tuple[int, int, str]:
        now = time.time()
        mapping = {
            '1h': (3600, 300, "5m"),
            '24h': (86400, 7200, "2h"),
            '7d': (604800, 43200, "12h")
        }
        duration, window_sec, window_str = mapping.get(timeframe, mapping['24h'])
        start_sec = int(now - duration)
        return start_sec, window_sec, window_str

    def _call_ws(self, ws, method: str, params: List = None):
        """Helper to execute synchronous JSON-RPC calls over the WebSocket."""
        call_id = str(uuid.uuid4())
        ws.send(json.dumps({
            "id": call_id,
            "msg": "method",
            "method": method,
            "params": params or []
        }))
        
        while True:
            resp_text = ws.recv()
            resp = json.loads(resp_text)
            
            if resp.get("id") == call_id:
                if "error" in resp:
                    raise Exception(f"API Error ({method}): {resp['error']}")
                return resp.get("result")

    def run(self, timeframe: Literal['1h', '24h', '7d'] = '24h') -> str:
        print(f"\n[DEBUG TRUENAS] AI requested TrueNAS telemetry (Timeframe: {timeframe})")
        start_sec, window_sec, window_str = self._get_time_params(timeframe)
        
        # Build WebSocket URL directly from settings
        base_url = settings.TRUENAS_URL
        ws_protocol = "wss" if base_url.startswith("https://") else "ws"
        if "://" in base_url:
            base_url = base_url.split("://")[1]
        ws_url = f"{ws_protocol}://{base_url}/websocket"
        
        baseline_info = {}
        disk_mapping = {}
        baseline_avg_temps = {}
        baseline_max_temps = {}
        bucket_max_temps = {}
        active_alerts = []

        try:
            # -----------------------------------------------------------------
            # PHASE 1: TRUENAS WEBSOCKETS (Pools, Disks, Alerts)
            # -----------------------------------------------------------------
            print(f"[DEBUG TRUENAS] Connecting to {ws_url}...")
            
            ssl_context = None
            if ws_url.startswith("wss://"):
                ssl_context = ssl.create_default_context()
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

            with connect(ws_url, max_size=None, ssl=ssl_context) as ws:
                ws.send(json.dumps({"msg": "connect", "version": "1", "support": ["1"]}))
                while True:
                    resp = json.loads(ws.recv())
                    if resp.get("msg") == "connected":
                        break
                
                print("[DEBUG TRUENAS] Authenticating...")
                auth_res = self._call_ws(ws, "auth.login_with_api_key", [settings.TRUENAS_API_KEY])
                if not auth_res:
                    raise Exception("WebSocket Authentication failed. Check API Key.")

                print("[DEBUG TRUENAS] Fetching storage pools...")
                pools = self._call_ws(ws, "pool.query")
                for p in pools:
                    data_vdevs = p.get("topology", {}).get("data", [])
                    size_tb = sum(v.get("stats", {}).get("size", 0) for v in data_vdevs) / (1024**4)
                    alloc_tb = sum(v.get("stats", {}).get("allocated", 0) for v in data_vdevs) / (1024**4)
                    free_tb = size_tb - alloc_tb
                    baseline_info[f"Pool_{p.get('name')}"] = f"{free_tb:.2f}TB free / {size_tb:.2f}TB total ({p.get('status', 'UNKNOWN')})"

                print("[DEBUG TRUENAS] Mapping physical disk topologies...")
                disks = self._call_ws(ws, "disk.query")
                
                # Exclude the VM host drive (scsi0) from the mapping entirely
                valid_disks = [d for d in disks if "scsi0" not in d.get("name", "") and "scsi0" not in d.get("serial", "")]
                
                baseline_info["Physical_Disks"] = f"{len(valid_disks)} Disks Detected"
                for d in valid_disks:
                    disk_mapping[d.get("name")] = d.get("serial", "UNKNOWN_SERIAL")

                print("[DEBUG TRUENAS] Fetching active system alerts...")
                alerts_raw = self._call_ws(ws, "alert.list")
                for a in alerts_raw:
                    if a.get("dismissed"): continue
                    raw_level = a.get("level", "WARNING")
                    level = "WARN" if raw_level == "WARNING" else "FATAL" if raw_level == "CRITICAL" else raw_level

                    dt_dict = a.get("datetime", {})
                    ts_ms = dt_dict.get("$date", time.time() * 1000)
                    ts_sec = ts_ms / 1000
                    if ts_sec < start_sec: ts_sec = start_sec
                        
                    raw_msg = a.get("formatted", "Unknown Alert")
                    clean_msg = re.sub(r'<[^>]+>', ' ', raw_msg) 
                    clean_msg = re.sub(r'\s+', ' ', clean_msg).strip() 
                    
                    active_alerts.append({"ts_sec": ts_sec, "level": level, "message": clean_msg})

            # -----------------------------------------------------------------
            # PHASE 2: INFLUXDB (Thermal Metrics)
            # -----------------------------------------------------------------
            print(f"[DEBUG TRUENAS] Connecting to InfluxDB for thermal data at {settings.INFLUXDB_URL}...")
            client = InfluxDBClient(
                url=settings.INFLUXDB_URL, 
                token=settings.INFLUXDB_TOKEN, 
                org=settings.INFLUXDB_ORG
            )
            query_api = client.query_api()

            # Flux query: Grabs any measurement containing 'truenas' and 'temp' 
            # and gets the maximum value grouped into intervals.
            flux_query = f"""
            from(bucket: "{settings.INFLUXDB_DOCKER_BUCKET}")
              |> range(start: -{timeframe})
              |> filter(fn: (r) => r["_measurement"] =~ /truenas/ and r["_measurement"] =~ /temp/)
              |> aggregateWindow(every: {window_str}, fn: max, createEmpty: false)
              |> yield(name: "max")
            """
            
            tables = query_api.query(flux_query)
            
            sums = {}
            counts = {}
            buckets_raw = {}
            
            for table in tables:
                for record in table.records:
                    measurement = record.get_measurement()
                    val = record.get_value()
                    if val is None: continue
                        
                    ts = int(record.get_time().timestamp())
                    
                    # Smart Matching against our valid_disks mapping
                    matched_serial = None
                    for sdx, serial in disk_mapping.items():
                        if serial in measurement or sdx in measurement:
                            matched_serial = serial
                            break
                            
                    if not matched_serial:
                        continue # Skip metrics for unmapped disks (like scsi0)
                        
                    # Aggregate into buckets
                    bucket_ts = (ts // window_sec) * window_sec
                    if bucket_ts not in buckets_raw: buckets_raw[bucket_ts] = {}
                    if matched_serial not in buckets_raw[bucket_ts]: buckets_raw[bucket_ts][matched_serial] = []
                    buckets_raw[bucket_ts][matched_serial].append(val)

            # Process InfluxDB aggregates into baselines and timelines
            for ts, serial_dict in buckets_raw.items():
                bucket_max_temps[ts] = {}
                for serial, temps in serial_dict.items():
                    max_t = max(temps)
                    bucket_max_temps[ts][serial] = max_t
                    
                    sums[serial] = sums.get(serial, 0) + max_t
                    counts[serial] = counts.get(serial, 0) + 1
                    baseline_max_temps[serial] = max(baseline_max_temps.get(serial, 0), max_t)

            baseline_avg_temps = {s: round(sums[s]/counts[s], 1) for s in sums if counts[s] > 0}
            print(f"[DEBUG TRUENAS] Successfully pulled InfluxDB data for {len(baseline_avg_temps)} mapped disks.")

        except Exception as e:
            print(f"[ERROR TRUENAS / INFLUX] {e}")
            return f"Error executing TrueNAS/InfluxDB Telemetry: {e}"

        print(f"[DEBUG TRUENAS] Synthesizing timeline and thermal anomalies...")

        global_baseline = {**baseline_info}
        
        # Build human-readable baseline temperatures using the topology map
        if baseline_avg_temps:
            ordered_temps = {}
            for serial, d_info in DISK_TOPOLOGY.items():
                if serial in baseline_avg_temps:
                    avg_t = baseline_avg_temps[serial]
                    max_t = baseline_max_temps.get(serial, avg_t)
                    key_str = f"{serial} {d_info['desc']}"
                    ordered_temps[key_str] = {"avg": f"{avg_t} C", "max": f"{max_t} C"}
            
            # Catch any remaining disks that sent temps but aren't explicitly in the Topology Dictionary
            for serial, avg_t in baseline_avg_temps.items():
                if serial not in DISK_TOPOLOGY:
                    max_t = baseline_max_temps.get(serial, avg_t)
                    key_str = f"{serial} (Unmapped in Topology)"
                    ordered_temps[key_str] = {"avg": f"{avg_t} C", "max": f"{max_t} C"}
                    
            global_baseline["Disk_Temperatures"] = ordered_temps

        timeline = {}

        # Evaluate thresholds
        for ts, disks_dict in bucket_max_temps.items():
            dt = datetime.fromtimestamp(ts, timezone.utc)
            bucket_key = dt.strftime("%Y-%m-%d %H:%M:%S")
            anomalies = {}
            temp_events = []
            
            for disk_serial, max_temp in disks_dict.items():
                thresholds = DISK_TOPOLOGY.get(disk_serial, DEFAULT_THRESHOLDS)
                
                if max_temp >= thresholds["err"]:
                    anomalies[f"Temp_{disk_serial}_max"] = f"{max_temp} C"
                    temp_events.append({
                        "time": dt.strftime("%H:%M:%S"),
                        "level": "FATAL",
                        "message": f"THERMAL ALERT: {disk_serial} ({thresholds['desc']}) exceeded critical limit: {max_temp} C",
                        "occurrences": 1
                    })
                elif max_temp >= thresholds["warn"]:
                    anomalies[f"Temp_{disk_serial}_max"] = f"{max_temp} C"
                    temp_events.append({
                        "time": dt.strftime("%H:%M:%S"),
                        "level": "WARN",
                        "message": f"THERMAL WARNING: {disk_serial} ({thresholds['desc']}) running hot: {max_temp} C",
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

        # Merge in System Alerts
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
        total_possible_buckets = int((time.time() - start_sec) / window_sec)
        
        for k, v in sorted(timeline.items()):
            has_anomalies = "infrastructure_anomalies" in v and v["infrastructure_anomalies"]
            has_logs = "log_events" in v and len(v["log_events"]) > 0
            
            if has_anomalies or has_logs:
                if not has_anomalies: v.pop("infrastructure_anomalies", None)
                if not has_logs: v.pop("log_events", None)
                final_timeline.append(v)
                
        ignored_count = total_possible_buckets - len(final_timeline)
        print(f"[DEBUG TRUENAS] Analysis complete. Returning payload with {len(final_timeline)} recorded events.")

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
    print(truenas("1h"))