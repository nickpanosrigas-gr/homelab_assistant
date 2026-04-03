# Home Lab AIOps Assistant: Master Architecture & Implementation Specification

This document serves as the complete architectural blueprint and technical specification for building a Python-based, LangGraph-orchestrated AIOps assistant for a Proxmox home lab. 

---

## 1. Core Constraints & Environmental Realities

* **Hardware Bottleneck:** The local LLM runs in an Ollama LXC (ID: 220) using a dynamically passed Nvidia RTX 2070 Super.
* **The "Gaming Override":** When the Windows 11 Gaming VM (ID: 130) starts, a Proxmox hook script automatically shuts down the Ollama LXC to reclaim the GPU for gaming.
* **Fast-Fail Requirement:** Because the AI goes offline during gaming sessions, all automated scripts (cron jobs) must first ping the Ollama API directly. If Ollama is unreachable, scripts must immediately execute a clean exit (`sys.exit(0)`) to prevent queue stalling and API timeouts.
* **Safety Principle:** The assistant is strictly **read-only**. It will not execute state-changing infrastructure commands.

---

## 2. Technology Stack

* **Language:** Python 3.11+
* **Dependency Management:** `uv` (the modern, extremely fast standard for Python project management).
* **AI Orchestration:** LangChain and LangGraph (implementing a Hierarchical ReAct pattern).
* **LLM Backend:** Local Ollama API (`ibm/granite4:micro-h-q8_0`).
* **Voice-to-Text:** Faster-Whisper Server (CPU-based transcription) running on the Linux Docker Host (VM 120).
* **Telemetry Sources:** InfluxDB (Metrics) and Loki (Logs), running on the Docker host.
* **User Interface:** Telegram Bot API (supports text, voice memos, and proactive alerts).

---

## 3. Domain-Driven Agent Architecture

To maximize speed, minimize token usage, and prevent ReAct hallucination loops, the architecture uses a **Hierarchical Agent Design**:

| Component | Role & Responsibility | Methodology |
| :--- | :--- | :--- |
| **Main Agent** | **The Flexible Router.** Analyzes the user's prompt, references server topology, and selects the right sub-agent to invoke. | Dynamic `create_react_agent` with conversational memory. |
| **Service Sub-Agents** | **Deterministic Data Gatherers.** Specialized scripts for specific services (e.g., Jellyfin, TrueNAS, Technitium). They execute hardcoded, parallel API checks (pings, logs, metrics) to guarantee accuracy. | "Dumb" Python functions that gather data upfront, ask the local LLM for a structured summary, and return text to the Main Agent. |

---

## 4. Core Workflows

### 4.1 Proactive Anomaly Detection (Frequent Cron Job)
Instead of scraping all APIs sequentially, the system leverages smart aggregation:
1.  **Hardware Check:** Ping the Ollama API. (If unresponsive -> `sys.exit(0)`).
2.  **Metric Filter:** Query InfluxDB via Flux for breached thresholds (e.g., `usage_percent > 90`).
3.  **Log Filter:** Query Loki via LogQL for high-severity logs (`{job=~".*"} |= "level=error"`) over the last interval.
4.  **Logic Gate:** If data is empty, exit cleanly. Do not invoke the LLM.
5.  **LLM Analysis:** Pass data to the Agent. The AI summarizes the cause and sends a **Telegram Alert** using the `send_telegram_alert` push function.

### 4.2 Interactive Querying (Telegram Bot Daemon)
1.  User sends a text or voice message to the Telegram bot.
2.  *(If Voice)*: Audio is routed to the local Faster-Whisper container for transcription.
3.  Message enters the LangGraph `State`.
4.  **Main Agent** analyzes the request and triggers the appropriate deterministic sub-agent tool (e.g., `check_jellyfin()`).
5.  The sub-agent executes all necessary API calls automatically, synthesizes a localized status report, and passes it back to the Main Agent.
6.  Main Agent formats the final conversational reply in the Telegram chat.

### 4.3 The Daily "CIO Digest" (Morning Cron Job)
1.  Runs daily in the morning to execute 24-hour telemetry queries.
2.  Passes data to the Agent for a "Director level" 3-bullet-point summary.
3.  Pushes the formatted Markdown report to Telegram.

---

## 5. Python Project Structure

```text
homelab_assistant/
├── pyproject.toml              # Dependency management strictly via `uv`
├── .env                        # API Keys, Tokens, IPs
├── data/
│   └── Proxmox.md              # RAG Source Document for baseline memory
├── scripts/
│   ├── check_anomalies.py      # Frequent anomaly cron job (Entry Point 1)
│   └── daily_digest.py         # Morning CIO digest cron job (Entry Point 2)
├── src/
│   ├── main.py                 # Telegram bot daemon (Entry Point 3)
│   ├── config/
│   │   └── settings.py         # Pydantic BaseSettings for env vars
│   ├── clients/                # API Wrappers (Fixed Templates)
│   │   ├── influxdb.py         # Flux queries for Proxmox/Telegraf buckets
│   │   ├── grafana_loki.py     # LogQL queries
│   │   ├── truenas.py          # TrueNAS REST API client
│   │   └── ping.py             # HTTP connectivity tester
│   ├── bot/                    
│   │   ├── telegram_app.py     # Bot daemon and push notification logic
│   │   └── whisper_stt.py      # Faster-Whisper API client
│   └── agent/                  
│       ├── graph.py            # LangGraph Main Agent & Tool Binding
│       ├── state.py            # TypedDict definition (inc. LangGraph internals)
│       ├── prompts.py          # Centralized System Prompts & Topology Context
│       └── sub_agents/         # Deterministic data-gathering tools
│           ├── jellyfin.py     
│           ├── navidrome.py    
│           ├── nginx.py        
│           ├── technitium.py   
│           ├── truenas.py      
│           └── vaultwarden.py
```

---

## 6. Required Configuration & Code Snippets

### 6.1 Environment Variables (`.env`)

```env
# Local AI Endpoints
OLLAMA_BASE_URL="[http://192.168.1.220:11434](http://192.168.1.220:11434)"
OLLAMA_MODEL="ibm/granite4:micro-h-q8_0"
WHISPER_API_URL="[http://192.168.1.120:8000/v1/audio/transcriptions](http://192.168.1.120:8000/v1/audio/transcriptions)"

# Telemetry Endpoints
INFLUXDB_URL="[http://192.168.1.120:8086](http://192.168.1.120:8086)"
INFLUXDB_TOKEN="your_token"
INFLUXDB_ORG="nick"
INFLUXDB_PROXMOX_BUCKET="proxmox"
INFLUXDB_DOCKER_BUCKET="telegraf"
LOKI_URL="[http://192.168.1.120:3100](http://192.168.1.120:3100)"

# Infrastructure
TRUENAS_IP="192.168.1.110"
TRUENAS_API_KEY="your_api_key"

# Telegram Bot
TELEGRAM_BOT_TOKEN="your_bot_token"
TELEGRAM_ALLOWED_USER_ID=123456789
```

### 6.2 LangGraph State Definition (`src/agent/state.py`)
```python
from typing import Annotated, Sequence
from typing_extensions import TypedDict, NotRequired
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AssistantState(TypedDict):
    """The core state object passed between LangGraph nodes."""
    # Appends new messages to the existing list (crucial for Telegram chat memory)
    messages: Annotated[Sequence[BaseMessage], add_messages]
    
    # Used by cronjobs to pass in raw anomaly data without clogging chat history
    context_data: NotRequired[dict]
    
    # --- LangGraph Internal Keys ---
    # Required by the prebuilt ReAct agent to prevent infinite loops
    is_last_step: NotRequired[bool]
    remaining_steps: NotRequired[int]
```

### 6.3 The Fast-Fail Hardware Check (`scripts/check_anomalies.py`)
```python
import sys
import requests
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def check_ollama_and_exit():
    """Pings Ollama directly. If unresponsive, assume AI is offline (gaming mode) and exit."""
    ollama_url = os.getenv("OLLAMA_BASE_URL", "[http://192.168.1.220:11434](http://192.168.1.220:11434)")
    
    try:
        # A simple GET request to Ollama's base endpoint to check if it is alive
        response = requests.get(ollama_url, timeout=5)
        response.raise_for_status()
    except requests.RequestException:
        print("Ollama is unreachable. AI offline (likely gaming). Canceling cron job.")
        sys.exit(0)

if __name__ == "__main__":
    check_ollama_and_exit()
    # Proceed with InfluxDB/Loki checks...
```

### 6.4 Docker Configuration for Voice-to-Text (Add to VM 120 Stack)
```yaml
services:
  whisper:
    image: fedirz/faster-whisper-server:latest
    container_name: whisper-api
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      # Use CPU-friendly model since GPU is passed through
      - WHISPER__MODEL=small 
    volumes:
      - /home/nick/docker/whisper/models:/root/.cache/huggingface
```