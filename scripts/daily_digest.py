import sys
import os
from pathlib import Path
import requests
from dotenv import load_dotenv

project_root = str(Path(__file__).parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()

from src.config.settings import settings
from src.bot.telegram_app import send_telegram_alert
from src.agent.graph import app as agent_app
from src.clients.influxdb import InfluxDBClient
from src.clients.truenas import TrueNASClient
from src.agent.prompts import DAILY_DIGEST_PROMPT

def check_ollama_and_exit():
    """Pings Ollama directly. If unresponsive, assume AI is offline (gaming mode) and exit."""
    try:
        response = requests.get(settings.OLLAMA_BASE_URL, timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        print("Ollama is unreachable. AI offline (likely gaming). Canceling morning digest.")
        sys.exit(0)

def main():
    # 1. Hardware Check
    check_ollama_and_exit()

    influx_client = InfluxDBClient()
    truenas_client = TrueNASClient()

    try:
        # 2. Fetch 24-hour telemetry across domains
        services_health = influx_client.get_container_metrics("all")
        pool_health = truenas_client.get_pool_health()
        active_alerts = truenas_client.get_alerts()
    except Exception as e:
        print(f"Digest telemetry fetch error: {e}")
        sys.exit(1)

    prompt = DAILY_DIGEST_PROMPT.format(
        services=services_health,
        pool=pool_health,
        alerts=active_alerts
    )

    try:
        # Pass the structured prompt to the graph
        ai_response = agent_app.invoke({
            "messages": [("user", prompt)],
            "context_data": {
                "services": services_health,
                "truenas_pool": pool_health,
                "truenas_alerts": active_alerts
            }
        })
        
        summary = ai_response["messages"][-1].content
        
        # 4. Push Notification
        digest_text = f"🌅 *Morning CIO Digest*\n\n{summary}"
        send_telegram_alert(digest_text)
        print("Daily digest generated and sent successfully.")
        
    except Exception as e:
        print(f"Agent analysis failed: {e}")
        sys.exit(1)
        
if __name__ == "__main__":
    main()