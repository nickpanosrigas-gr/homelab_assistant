import sys
import os
from pathlib import Path
import requests
from dotenv import load_dotenv

project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    
# Load environment variables first
load_dotenv()

from src.config.settings import settings
from src.bot.telegram_app import send_telegram_alert
from src.agent.graph import app as agent_app
from src.clients.influxdb import InfluxDBClient
from src.clients.loki import LokiClient

def check_ollama_and_exit():
    """Pings Ollama directly. If unresponsive, assume AI is offline (gaming mode) and exit."""
    try:
        response = requests.get(settings.OLLAMA_BASE_URL, timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        print("Ollama is unreachable. AI offline (likely gaming). Canceling cron job.")
        sys.exit(0)

def main():
    # 1. Hardware Check
    check_ollama_and_exit()

    influx_client = InfluxDBClient()
    loki_client = LokiClient()

    try:
        # 2. Metric Filter: Query InfluxDB for breached thresholds
        # Note: Update the client method if you built a specific anomaly-only query in influxdb.py
        metric_anomalies = influx_client.get_container_metrics("anomalies_only") 
        
        # 3. Log Filter: Query Loki via LogQL for high-severity logs over the last interval
        log_errors = loki_client.get_container_logs('{job=~".*"} |= "level=error"')
    except Exception as e:
        print(f"Telemetry fetch error: {e}")
        sys.exit(1)

    # 4. Logic Gate: If data is empty (no anomalies), exit cleanly. Do not invoke the LLM.
    if not metric_anomalies and not log_errors:
        print("System nominal. No anomalies detected. Exiting cleanly.")
        sys.exit(0)

    # 5. LLM Analysis
    # We construct a direct prompt wrapping the telemetry data and pass it to the LangGraph app
    prompt = (
        "You are an AIOps assistant. Review the following anomaly data consisting of high metrics and error logs.\n"
        "Briefly summarize the root cause and identify any failing services. Keep it concise for a push notification.\n\n"
        f"**Metrics Data:**\n{metric_anomalies}\n\n"
        f"**Log Errors:**\n{log_errors}"
    )

    try:
        # Pass the raw data into context_data as specified in the README state definition
        ai_response = agent_app.invoke({
            "messages": [("user", prompt)],
            "context_data": {
                "metrics": metric_anomalies,
                "logs": log_errors
            }
        })
        
        summary = ai_response["messages"][-1].content
        
        # 6. Push Notification via Telegram Bot Daemon logic
        alert_text = f"🚨 *Proactive Anomaly Detected*\n\n{summary}"
        send_telegram_alert(alert_text)
        print("Alert generated and sent successfully.")
        
    except Exception as e:
        print(f"Agent analysis failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()