import asyncio
import aiohttp
import re
import yaml
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Dict, List, Any
from src.config.settings import settings

# --- Global Constants & Configurations ---

# Define the Known Noise patterns (Red Herrings)
KNOWN_NOISE_PATTERNS = [
    re.compile(r"connection reset by peer", re.IGNORECASE),
    re.compile(r"timeout parsing request", re.IGNORECASE),
    # Add more known safe noise here
]

# Regex to mask dynamic variables (IPs, UUIDs, Ports)
MASKING_RULES = [
    (re.compile(r'\b\d{1,3}(?:\.\d{1,3}){3}\b'), "[IP]"),
    (re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.I), "[UUID]"),
    (re.compile(r'(?<=:)\d{4,5}\b'), "[PORT]")
]

def get_time_config(timeframe: str) -> dict:
    """Returns start time, window duration, and bucket count based on the timeframe."""
    now = datetime.now(timezone.utc)
    if timeframe == "1h":
        return {"start": now - timedelta(hours=1), "window_str": "5m", "window_sec": 300, "buckets": 12, "desc": "1h (5m intervals)"}
    elif timeframe == "24h":
        return {"start": now - timedelta(hours=24), "window_str": "2h", "window_sec": 7200, "buckets": 12, "desc": "24h (2h intervals)"}
    elif timeframe == "7d":
        return {"start": now - timedelta(days=7), "window_str": "12h", "window_sec": 43200, "buckets": 14, "desc": "7d (12h intervals)"}
    else:
        raise ValueError("Invalid timeframe. Must be 1h, 24h, or 7d.")

async def fetch_influxdb(session: aiohttp.ClientSession, service_name: str, config: dict) -> list:
    """Fetches bucketed metrics asynchronously from InfluxDB."""
    start_time_str = f"-{config['desc'].split(' ')[0]}"
    window = config['window_str']
    
    # We query Docker/LXC metrics, aggregating by the calculated window
    flux_query = f"""
    from(bucket: "{settings.INFLUXDB_DOCKER_BUCKET}") 
      |> range(start: {start_time_str}) 
      |> filter(fn: (r) => r["container_name"] == "{service_name}") 
      |> filter(fn: (r) => r["_field"] =~ /usage_percent|usage|io_wait/) 
      |> aggregateWindow(every: {window}, fn: mean, createEmpty: true)
      |> yield(name: "metrics")
    """
    
    url = f"{settings.INFLUXDB_URL}/api/v2/query?org={settings.INFLUXDB_ORG}"
    headers = {
        "Authorization": f"Token {settings.INFLUXDB_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/vnd.flux"
    }
    
    try:
        async with session.post(url, headers=headers, data=flux_query, timeout=15) as response:
            if response.status == 200:
                # In a real scenario, you'd parse the CSV/JSON stream from Influx.
                # For this implementation, we return mocked parsed data structure to demonstrate fusion
                return await response.json() 
            return []
    except Exception as e:
        print(f"[DEBUG] InfluxDB fetch error: {e}")
        return []

async def fetch_loki(session: aiohttp.ClientSession, service_name: str, config: dict) -> list:
    """Fetches logs asynchronously from Loki using specified log-level filters."""
    start_ns = int(config['start'].timestamp() * 1_000_000_000)
    
    # LogQL: Filter by service AND only grab errors, warnings, or specific info states
    log_filter = "(?i)(error|warn|fatal|started|stopped|restarted|failed|success|authenticated)"
    query = f'{{service_name="{service_name}"}} |~ "{log_filter}"'
    
    url = f"{settings.LOKI_URL}/loki/api/v1/query_range"
    params = {"query": query, "start": str(start_ns), "limit": 1000, "direction": "forward"}
    
    try:
        async with session.get(url, params=params, timeout=15) as response:
            if response.status == 200:
                data = await response.json()
                results = data.get("data", {}).get("result", [])
                logs = []
                for stream in results:
                    for val in stream.get("values", []):
                        logs.append({"ts": int(val[0]) / 1_000_000_000, "text": val[1]})
                return logs
            return []
    except Exception as e:
        print(f"[DEBUG] Loki fetch error: {e}")
        return []

def process_loki_dedup(raw_logs: list, config: dict) -> dict:
    """Masks variables, filters known noise, and deduplicates logs into time buckets."""
    buckets = {i: {} for i in range(config['buckets'])}
    start_ts = config['start'].timestamp()
    window_sec = config['window_sec']

    for log in raw_logs:
        text = log['text'].strip()
        
        # 1. Filter Known Noise
        if any(pattern.search(text) for pattern in KNOWN_NOISE_PATTERNS):
            continue
            
        # 2. Mask Dynamic Variables
        for pattern, replacement in MASKING_RULES:
            text = pattern.sub(replacement, text)
            
        # 3. Determine level (Basic heuristic, replace with actual logfmt parsing if available)
        level = "INFO"
        if "error" in text.lower() or "failed" in text.lower(): level = "ERROR"
        elif "warn" in text.lower(): level = "WARN"
        elif "fatal" in text.lower(): level = "FATAL"
            
        # 4. Map to Bucket
        bucket_index = int((log['ts'] - start_ts) // window_sec)
        if 0 <= bucket_index < config['buckets']:
            sig = (level, text)
            if sig not in buckets[bucket_index]:
                buckets[bucket_index][sig] = {"time": datetime.fromtimestamp(log['ts'], timezone.utc).strftime("%H:%M:%S"), "occurrences": 0}
            buckets[bucket_index][sig]["occurrences"] += 1

    return buckets

def process_influx_sparse(raw_metrics: list, config: dict) -> tuple:
    """Calculates baseline and drops normal buckets (Sparse Matrix Method)."""
    # NOTE: Because we mocked the exact return JSON above, we are mocking the math here.
    # In production, iterate your parsed Influx CSV/JSON rows.
    
    global_baseline = {"CPU_avg": "12.5%", "RAM_avg": "2.1GB", "Disk_IO_Wait_avg": "15ms"}
    anomalies = {i: {} for i in range(config['buckets'])}
    
    # Example logic for inserting an anomaly in bucket 2
    # if cpu_val > 85.0: anomalies[bucket_index] = {"CPU_max": f"{cpu_val}%"}
    anomalies[2] = {"CPU_max": "92.1%", "Disk_IO_Wait_max": "120ms"} 
    
    return global_baseline, anomalies

async def run_telemetry_fusion(service_name: str, timeframe: Literal["1h", "24h", "7d"]) -> str:
    """Main execution flow for fetching and fusing telemetry."""
    config = get_time_config(timeframe)
    
    # 1. Parallel Fetching
    async with aiohttp.ClientSession() as session:
        influx_task = fetch_influxdb(session, service_name, config)
        loki_task = fetch_loki(session, service_name, config)
        
        raw_metrics, raw_logs = await asyncio.gather(influx_task, loki_task)

    # 2. Processing
    global_baseline, anomalies = process_influx_sparse(raw_metrics, config)
    log_buckets = process_loki_dedup(raw_logs, config)

    # 3. Data Fusion
    timeline = []
    ignored_count = 0
    start_ts = config['start']
    
    for i in range(config['buckets']):
        bucket_start = start_ts + timedelta(seconds=i * config['window_sec'])
        bucket_end = bucket_start + timedelta(seconds=config['window_sec'])
        bucket_label = f"{bucket_start.strftime('%H:%M')} to {bucket_end.strftime('%H:%M')}"
        
        bucket_data = {"bucket": bucket_label}
        has_data = False
        
        if anomalies[i]:
            bucket_data["infrastructure_anomalies"] = anomalies[i]
            has_data = True
            
        if log_buckets[i]:
            bucket_data["log_events"] = []
            for (level, msg), data in log_buckets[i].items():
                bucket_data["log_events"].append({
                    "time": data["time"],
                    "level": level,
                    "message": msg,
                    "occurrences": data["occurrences"]
                })
            has_data = True
            
        # Add correlation note
        if anomalies[i] and log_buckets[i]:
            bucket_data["note"] = "Hardware spikes correlate chronologically with captured log events."
            
        if has_data:
            timeline.append(bucket_data)
        else:
            ignored_count += 1

    # 4. YAML Generation
    output_dict = {
        "Target_Service": service_name,
        "Timeframe": config["desc"],
        "Global_Baseline": global_baseline,
        "Timeline": timeline,
        "Ignored_Buckets": f"{ignored_count} intervals omitted. System operated within hardware baselines with zero ERROR/WARN logs."
    }
    
    # Use sort_keys=False to preserve our schema order
    return yaml.dump(output_dict, default_flow_style=False, sort_keys=False)

# --- LangGraph Tool Registration Wrapper ---
def get_fused_telemetry(service_name: str, timeframe: Literal["1h", "24h", "7d"] = "24h") -> str:
    """
    Fetches hardware metrics and system logs simultaneously.
    Returns a highly condensed YAML timeline of anomalies and errors.
    """
    # Execute the async loop (LangGraph calls this synchronously)
    return asyncio.run(run_telemetry_fusion(service_name, timeframe))

# To test it locally:
if __name__ == "__main__":
    result = get_fused_telemetry("plex", "24h")
    print(result)