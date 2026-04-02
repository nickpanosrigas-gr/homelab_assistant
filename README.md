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
* **Dependency Management:** `uv` or `Poetry` (modern package management, do not use raw `pip`).
* **AI Orchestration:** LangChain and LangGraph (implementing a Supervisor/Mediator state machine pattern).
* **LLM Backend:** Local Ollama API (`ibm/granite4:micro-h-q8_0`).
* **Voice-to-Text:** Faster-Whisper Server (CPU-based transcription) running on the Linux Docker Host (VM 120).
* **Telemetry Sources:** Prometheus (Metrics) and Loki (Logs), already running on the Docker host.
* **User Interface:** Telegram Bot API (supports text and voice memos).

---

## 3. Domain-Driven Agent Architecture

To prevent LLM context confusion and tool duplication, the LangGraph architecture uses a Supervisor pattern routing to Domain-Specific Sub-Agents, rather than Application-Specific agents.

| Agent Name | Role & Responsibility | Example Tools Provided |
| :--- | :--- | :--- |
| **Main Supervisor** | **The Router.** Analyzes the prompt, checks RAG memory, and delegates to the appropriate domain agent. | *None (Routing only)* |
| **Virtualization Agent** | **Proxmox Monitor.** Handles the Proxmox Host, Windows VM (130), TrueNAS VM (110), Docker VM (120), and all LXCs (Technitium 200, Jellyfin 210, Ollama 220). | `get_vm_state()`, `get_node_cpu()` |
| **Container Agent** | **Docker Stack Monitor.** Handles all Dockerized services running inside VM 120 (Arr Stack, n8n, Vaultwarden, Navidrome, Nginx, etc.). | `query_loki(app_name)`, `query_prom(app_name)` |
| **Storage Agent** | **TrueNAS Monitor.** Handles ZFS pool health, VDEV capacity, and disk I/O on the TrueNAS VM. | `get_zfs_health()`, `get_pool_capacity()` |

---

## 4. Core Workflows

### 4.1 Proactive Anomaly Detection (Frequent Cron Job)
Instead of scraping all APIs sequentially, the system leverages smart aggregation:
1.  **Hardware Check:** Ping the Ollama API (`OLLAMA_BASE_URL`). (If unresponsive -> `sys.exit(0)`).
2.  **Metric Filter:** Query Prometheus via PromQL for breached thresholds (e.g., `up == 0`, `cpu_usage_percent > 90 for 5m`).
3.  **Log Filter:** Query Loki via LogQL for high-severity logs (`{job=~".*"} |= "level=error" or "level=fatal"`) over the last interval.
4.  **Logic Gate:** If JSON payloads from steps 2 & 3 are empty, exit cleanly. Do not invoke the LLM.
5.  **LLM Analysis:** Pass the filtered JSON to the LangGraph Supervisor. The LLM summarizes the root cause and sends a Telegram alert.

### 4.2 Interactive Querying (Telegram Bot Daemon)
1.  User sends a text or voice message to the Telegram bot.
2.  *(If Voice)*: Audio is routed to the local Faster-Whisper container API for transcription.
3.  Message text enters the LangGraph `State` (which retains conversation history).
4.  Supervisor routes to the correct Domain Agent, which uses its tools to fetch live data.
5.  Agent replies contextually in the Telegram chat.

### 4.3 The Daily "CIO Digest" (Morning Cron Job)
1.  Runs daily in the morning.
2.  Executes 24-hour PromQL/LogQL queries (e.g., 24h average temperatures, storage growth, total error counts).
3.  Passes data to the Main Supervisor with the prompt: *"Act as an IT Director. Analyze this 24-hour telemetry JSON. Provide a 3-bullet-point executive summary of the homelab's health, highlighting negative trends. Do not execute tools."*
4.  Pushes the formatted Markdown report to Telegram.

---

## 5. Python Project Structure

```text
homelab_assistant/
├── pyproject.toml              # Dependency management (uv/Poetry)
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
│   ├── clients/                # API Wrappers
│   │   ├── proxmox.py          
│   │   ├── grafana_loki.py     
│   │   └── prometheus.py       
│   ├── bot/                    
│   │   ├── telegram_app.py     # Bot routing
│   │   └── whisper_stt.py      # Faster-Whisper API client
│   └── agent/                  
│       ├── graph.py            # LangGraph routing logic
│       ├── state.py            # TypedDict definition
│       ├── prompts.py          # System prompts for agents
│       └── sub_agents/         # Domain-specific tools
│           ├── virtualization.py
│           ├── containers.py
│           └── storage.py
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
PROMETHEUS_URL="[http://192.168.1.120:9090](http://192.168.1.120:9090)"
LOKI_URL="[http://192.168.1.120:3100](http://192.168.1.120:3100)"

# Telegram Bot
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_ID=
```

### 6.2 LangGraph State Definition (`src/agent/state.py`)
```python
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class AssistantState(TypedDict):
    # Appends new messages to the existing list (crucial for Telegram chat memory)
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # Used by cronjobs to pass in raw anomaly data without clogging chat history
    context_data: dict 
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
    # Proceed with Prometheus/Loki checks...
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