import time
import requests
from datetime import datetime, timezone
from typing import Literal
from src.config.settings import settings

class LokiClient:
    def __init__(self):
        self.url = f"{settings.LOKI_URL}/loki/api/v1/query_range"

    def get_container_logs(self, service_name: str, timeframe: Literal['day', 'week', 'month'] = 'day') -> str:
        """
        Use to fetch system logs for troubleshooting. 
        Automatically deduplicates spammy logs and formats them chronologically for AI analysis.
        """
        clean_service_name = service_name.strip()
        print(f"\n[DEBUG LOKI] AI requested logs for: {clean_service_name} over timeframe: {timeframe}")
        
        # 1. Determine the start time in nanoseconds
        now = time.time()
        if timeframe == 'day':
            seconds_back = 24 * 60 * 60
        elif timeframe == 'week':
            seconds_back = 7 * 24 * 60 * 60
        elif timeframe == 'month':
            seconds_back = 30 * 24 * 60 * 60
        else:
            return "Error: timeframe must be 'day', 'week', or 'month'."
            
        start_time_ns = int((now - seconds_back) * 1_000_000_000)

        # 2. LogQL Filter (Exclude common noise)
        query = f'{{service_name="{clean_service_name}"}} != "healthcheck" != "DEBUG" != "TRACE"'

        params = {
            "query": query,
            "limit": 200, # Increased slightly since we are deduplicating
            "start": str(start_time_ns),
            "direction": "backward" # Gets the most recent X logs in the timeframe
        }

        try:
            response = requests.get(self.url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = data.get("data", {}).get("result", [])
            
            if not results:
                return f"No logs found for service: {clean_service_name} in the last {timeframe}."
            
            # 3. Extract and sort chronologically
            raw_logs = []
            for stream in results:
                for val in stream.get("values", []):
                    # val[0] is string nanoseconds, val[1] is the log string
                    timestamp_sec = int(val[0]) / 1_000_000_000
                    log_text = val[1].strip()
                    if log_text:
                        raw_logs.append((timestamp_sec, log_text))
            
            # Sort ascending (oldest to newest) to read like a story
            raw_logs.sort(key=lambda x: x[0])

            # 4. Consecutive Deduplication (Token Saver)
            compressed_logs = []
            if raw_logs:
                current_text = raw_logs[0][1]
                start_ts = raw_logs[0][0]
                last_ts = raw_logs[0][0]
                repeat_count = 1

                def format_timestamp(ts):
                    return datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')

                for ts, text in raw_logs[1:]:
                    if text == current_text:
                        repeat_count += 1
                        last_ts = ts
                    else:
                        # Yield the previous log block
                        time_str = f"[{format_timestamp(start_ts)} UTC]"
                        if repeat_count > 1:
                            duration = int(last_ts - start_ts)
                            compressed_logs.append(f"{time_str} {current_text} \n   -> (Repeated {repeat_count} times over {duration} seconds)")
                        else:
                            compressed_logs.append(f"{time_str} {current_text}")
                        
                        # Reset for new log
                        current_text = text
                        start_ts = ts
                        last_ts = ts
                        repeat_count = 1
                
                # Append the very last item
                time_str = f"[{format_timestamp(start_ts)} UTC]"
                if repeat_count > 1:
                    duration = int(last_ts - start_ts)
                    compressed_logs.append(f"{time_str} {current_text} \n   -> (Repeated {repeat_count} times over {duration} seconds)")
                else:
                    compressed_logs.append(f"{time_str} {current_text}")

            # 5. Format payload for the LLM
            llm_payload = (
                f"SYSTEM LOGS REPORT: {clean_service_name}\n"
                f"Timeframe Context: Most recent 200 relevant events from the last {timeframe.capitalize()}\n"
                "Note: Identical consecutive logs have been compressed to save space. Use timestamps to cross-reference with metrics.\n"
                "--------------------------------------------------\n"
                + "\n".join(compressed_logs) + "\n"
                "--------------------------------------------------\n"
                "End of logs."
            )

            print(f"[DEBUG LOKI] Successfully formatted {len(compressed_logs)} log blocks.")
            return llm_payload
            
        except requests.exceptions.RequestException as e:
            return f"Error fetching logs for {clean_service_name}: {str(e)}"