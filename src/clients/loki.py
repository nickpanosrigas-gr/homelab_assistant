import time
import requests
import re
from datetime import datetime, timezone
from typing import Literal, Dict, List
from collections import defaultdict
from src.config.settings import settings

class LokiClient:
    def __init__(self):
        self.loki_url = f"{settings.LOKI_URL}/loki/api/v1/query_range"
        self.influx_url = f"{settings.INFLUXDB_URL}/api/v2/query?org={settings.INFLUXDB_ORG}"
        self.influx_headers = {
            "Authorization": f"Token {settings.INFLUXDB_TOKEN}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux"
        }

    def _get_system_state(self) -> dict:
        """Fetches high-level system state from InfluxDB."""
        # Simple Flux query to grab latest disk, mem, and uptime from the Proxmox bucket
        flux_query = f"""
        from(bucket: "{settings.INFLUXDB_PROXMOX_BUCKET}")
          |> range(start: -5m)
          |> filter(fn: (r) => r["_measurement"] == "system")
          |> filter(fn: (r) => r["_field"] == "uptime" or r["_field"] == "disk_used_percent" or r["_field"] == "mem_used_percent")
          |> last()
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        """
        state = {"uptime": "Unknown", "disk_usage": "Unknown", "memory_usage": "Unknown"}
        try:
            res = requests.post(self.influx_url, headers=self.influx_headers, data=flux_query, timeout=5)
            if res.status_code == 200:
                lines = res.text.splitlines()
                if len(lines) > 1:
                    # Very basic CSV parsing for the last row
                    headers = lines[0].split(',')
                    values = lines[-1].split(',')
                    data_dict = dict(zip(headers, values))
                    
                    if "uptime" in data_dict:
                        # Assuming uptime is in seconds
                        uptime_sec = int(float(data_dict["uptime"]))
                        days = uptime_sec // 86400
                        state["uptime"] = f"{days} days"
                    if "disk_used_percent" in data_dict:
                        state["disk_usage"] = f"{float(data_dict['disk_used_percent']):.1f}%"
                    if "mem_used_percent" in data_dict:
                        state["memory_usage"] = f"{float(data_dict['mem_used_percent']):.1f}%"
        except Exception as e:
            print(f"[DEBUG] Failed to fetch system state from InfluxDB: {e}")
        return state

    def _mask_log(self, text: str) -> str:
        """Masks highly dynamic variables for better deduplication."""
        # Mask IPs
        text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', text)
        # Mask UUIDs
        text = re.sub(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', '[UUID]', text, flags=re.IGNORECASE)
        # Mask Hex Pointers/IDs (e.g., 0x7f8b9a)
        text = re.sub(r'\b0x[0-9a-fA-F]+\b', '[HEX_ID]', text)
        return text

    def _truncate_stack_trace(self, text: str) -> str:
        """Truncates logs exceeding 10 lines."""
        lines = text.split('\n')
        if len(lines) > 10:
            omitted = len(lines) - 6
            return '\n'.join(lines[:3] + [f"[... {omitted} lines omitted ...]"] + lines[-3:])
        return text

    def _parse_level(self, text: str) -> str:
        """Attempts to identify the log level."""
        match = re.search(r'\b(FATAL|CRITICAL|ERROR|WARN|WARNING|INFO|DEBUG|TRACE)\b', text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
        return "UNKNOWN"

    def get_logs(self, service_name: str, timeframe: Literal['1h', '24h', '7d'] = '1h') -> str:
        """
        LLM-Driven Loki Log Analyzer. Fetches, sanitizes, and deduplicates logs into a strict YAML payload.
        """
        clean_service_name = service_name.strip()
        
        # 1. Timeframe Calculation
        now = time.time()
        if timeframe == '1h':
            seconds_back = 3600
        elif timeframe == '24h':
            seconds_back = 86400
        elif timeframe == '7d':
            seconds_back = 7 * 86400
        else:
            return "Error: timeframe must be '1h', '24h', or '7d'."
            
        start_time_ns = int((now - seconds_back) * 1_000_000_000)
        end_time_ns = int(now * 1_000_000_000)

        start_date_str = datetime.fromtimestamp(now - seconds_back, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        end_date_str = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        # 2. LogQL Query
        if clean_service_name.lower() == 'all':
             query = '{container_name=~".+"} != "healthcheck" != "DEBUG" != "TRACE"'
        else:
             query = f'{{container_name="{clean_service_name}"}} != "healthcheck" != "DEBUG" != "TRACE"'

        params = {
            "query": query,
            "limit": 5000, # Grab a larger chunk to allow Python filtering
            "start": str(start_time_ns),
            "end": str(end_time_ns),
            "direction": "backward"
        }

        try:
            response = requests.get(self.loki_url, params=params, timeout=15)
            response.raise_for_status()
            results = response.json().get("data", {}).get("result", [])
        except Exception as e:
            return f"Error fetching logs from Loki: {str(e)}"

        # 3. Filtering & Processing Pipeline
        buckets = defaultdict(lambda: {"events": {}, "errors": 0, "warnings": 0, "total_logs": 0})
        
        info_keywords = re.compile(r'\b(started|stopped|failed|success|logged in|authenticated)\b', re.IGNORECASE)

        for stream in results:
            for val in stream.get("values", []):
                timestamp_sec = int(val[0]) / 1_000_000_000
                dt = datetime.fromtimestamp(timestamp_sec, timezone.utc)
                bucket_key = dt.strftime('%Y-%m-%d')
                time_str = dt.strftime('%H:%M:%S')
                
                raw_text = val[1].strip()
                if not raw_text:
                    continue

                level = self._parse_level(raw_text)
                
                # Filtering Logic
                if level in ["DEBUG", "TRACE"]:
                    continue
                if level in ["INFO", "UNKNOWN"] and not info_keywords.search(raw_text):
                    continue # Drop routine info

                # Masking & Truncation
                masked_text = self._mask_log(raw_text)
                final_text = self._truncate_stack_trace(masked_text)
                
                # Deduplication Key
                dedup_key = f"{level}:{final_text}"
                
                bucket = buckets[bucket_key]
                bucket["total_logs"] += 1
                
                if level in ["ERROR", "FATAL", "CRITICAL"]:
                    bucket["errors"] += 1
                elif level in ["WARN", "WARNING"]:
                    bucket["warnings"] += 1

                if dedup_key in bucket["events"]:
                    bucket["events"][dedup_key]["occurrences"] += 1
                    # Keep the most recent time
                    bucket["events"][dedup_key]["time"] = time_str
                else:
                    bucket["events"][dedup_key] = {
                        "time": time_str,
                        "level": level,
                        "message": final_text,
                        "occurrences": 1
                    }

        # 4. Fetch System State
        system_state = self._get_system_state()

        # 5. Assemble Strict YAML Payload
        yaml_lines = [
            "Context: Homelab Log Analysis",
            f"Target_Service: {clean_service_name}",
            f"Timeframe: {start_date_str} to {end_date_str}",
            "",
            "System_State:",
            f"  uptime: {system_state['uptime']}",
            f"  disk_usage: {system_state['disk_usage']}",
            f"  memory_usage: {system_state['memory_usage']}",
            "",
            "Data:"
        ]

        if not buckets:
            yaml_lines.append("  - bucket: No relevant logs found after filtering.")
        else:
            # Sort buckets chronologically
            for date_key in sorted(buckets.keys(), reverse=True):
                b_data = buckets[date_key]
                yaml_lines.append(f"  - bucket: {date_key}")
                yaml_lines.append("    summary:")
                yaml_lines.append(f"      total_logs: {b_data['total_logs']}")
                yaml_lines.append(f"      errors: {b_data['errors']}")
                yaml_lines.append(f"      warnings: {b_data['warnings']}")
                yaml_lines.append("    events:")
                
                # Sort events by occurrences (highest first) to highlight spammy errors
                sorted_events = sorted(b_data["events"].values(), key=lambda x: x["occurrences"], reverse=True)
                
                for ev in sorted_events:
                    yaml_lines.append(f"      - time: {ev['time']}")
                    yaml_lines.append(f"        level: {ev['level']}")
                    
                    # Safely quote the message string for YAML
                    safe_msg = ev['message'].replace('"', '\\"').replace('\n', '\\n')
                    yaml_lines.append(f"        message: \"{safe_msg}\"")
                    yaml_lines.append(f"        occurrences: {ev['occurrences']}")

        return "\n".join(yaml_lines)