# Home Lab AIOps Assistant: Master Architecture & Implementation Specification

This document serves as the complete architectural blueprint and technical specification for building a Python-based, LangGraph-orchestrated AIOps assistant for a Proxmox home lab. 

---

## 1. Core Constraints & Environmental Realities

* **Cloud Reasoning / High Availability:** The core reasoning LLM has been migrated to **Gemini 3.1 Flash Lite preview**, ensuring fast inference, large context windows, and continuous uptime regardless of local hardware states.
* **The "Gaming Override" (Embeddings Only):** The local Ollama LXC (ID: 220) using a dynamically passed Nvidia RTX 2070 Super is now strictly dedicated to generating vector embeddings for the local knowledge base. When the Windows 11 Gaming VM (ID: 130) starts, Ollama is shut down to reclaim the GPU. During this time, the assistant remains fully functional for querying and troubleshooting, though new documentation cannot be embedded until the GPU is released.
* **Safety Principle:** The assistant is strictly **read-only**. It will not execute state-changing infrastructure commands.

---

## 2. Technology Stack

* **Language:** Python 3.11+
* **Dependency Management:** `uv` (the modern, extremely fast standard for Python project management).
* **AI Orchestration:** LangChain and LangGraph (Unified ReAct Agent pattern).
* **LLM Backend:** Gemini 3.1 Flash Lite preview.
* **Vector Embeddings:** Local Ollama API `nomic-embed-text`.
* **Vector Database:** Qdrant (Knowledge retrieval).
* **LLM Observability:** Langfuse (Tracing, metrics, and prompt management).
* **Voice-to-Text:** Speaches (CPU-based Whisper inference) running on the Linux Docker Host.
* **Telemetry Sources:** InfluxDB (Hardware Metrics) and Loki (Application Logs).
* **User Interface:** Telegram Bot API (supports text, voice memos, and proactive alerts).

---

## 3. System Architecture & Tooling

To simplify execution and leverage the context window of Gemini 3.1 Flash Lite, the previous multi-agent architecture has been replaced with a **Unified Agent Model**. The agent dynamically accesses a centralized suite of specialized tools.

### Core Tools (`tools.py` & Tool Modules)

| Tool | Role & Responsibility |
| :--- | :--- |
| `ping(service_name)` | **Connectivity Tester.** Executes a quick ICMP/HTTP check against known internal endpoints to verify basic uptime. |
| `telemetry(service_name, timeframe)` | **The Fused Telemetry Aggregator.** A high-efficiency script that queries Loki and InfluxDB in parallel. It calculates dynamic baselines, discards normal hardware metrics, smart-deduplicates masked logs, and outputs a highly compressed, time-aligned YAML matrix for the LLM. |
| `qdrant.py` | **RAG Knowledge Engine.** Queries the `homelab_assistant` collection. Provides the LLM with context from stored Docker Compose files, Proxmox scripts, application runbooks, network topology, and setup information. |
| `truenas.py` | **Storage API Client.** Direct interaction with the TrueNAS REST API to pull zpool health, dataset capacities, and alert statuses. |

---

## 4. Core Workflows

### 4.1 Proactive Anomaly Detection (Frequent Cron Job)
1.  **Telemetry Aggregation:** Calls the `telemetry` tool (e.g., `timeframe="1h"`).
2.  **Logic Gate:** The tool filters out all baseline/normal behavior. If the resulting YAML is empty (no spikes, no ERROR/WARN logs), the script exits cleanly. Do not invoke the LLM.
3.  **LLM Analysis:** If anomalies exist, pass the YAML payload to Gemini. The AI references `qdrant.py` for context on the failing service.
4.  **Notification:** The AI summarizes the cause and sends a **Telegram Alert** using a push function.

### 4.2 Interactive Querying (Telegram Bot Daemon)
1.  User sends a text or voice message to the Telegram bot.
2.  *(If Voice)*: Audio is routed to the local Speaches container for transcription.
3.  Message enters the LangGraph `State`.
4.  **Agent Analysis:** Gemini analyzes the request, queries `qdrant.py` for environment specifics, and triggers `telemetry`, `ping`, or `truenas.py` to gather live data.
5.  **Synthesis:** The Agent synthesizes the retrieved telemetry with its RAG knowledge to formulate a solution or status report.
6.  **Response:** The Agent formats the final conversational reply in the Telegram chat, while execution traces are logged to Langfuse.

---

## 5. Fused Telemetry Aggregator Specification

The `telemetry(service_name, timeframe)` tool strictly enforces LLM token efficiency. 

* **Time Bucketing:** Divides timeframes into fixed intervals (`1h` -> 5m buckets, `24h` -> 2h buckets, `7d` -> 12h buckets).
* **Hardware Matrix (InfluxDB):** Calculates a `Global_Baseline` across the timeframe. Hardware metrics (CPU, RAM, Disk IO) are only included in a bucket if they breach dynamically calculated thresholds (e.g., > 30% higher than baseline).
* **Log Scrubbing (Loki):** Fetches only ERROR, WARN, FATAL (and specific state-change INFO logs). Masks highly dynamic variables (IPs, timestamps, ports) via regex and groups identical logs by count.
* **Output Format:** Strict, time-aligned YAML schema. If a bucket is entirely normal, it is omitted and added to an `Ignored_Buckets` count.

**Target Output YAML Schema:**
```yaml
Target_Service: string
Timeframe: string (e.g., "24h (2h intervals)")

Global_Baseline:
  CPU_avg: string
  RAM_avg: string
  Disk_IO_Wait_avg: string

Timeline:
  - bucket: string (e.g., "14:00 to 16:00")
    infrastructure_anomalies: # Omit entirely if no dynamic hardware spikes exist in this bucket
      CPU_max: string
      Disk_IO_Wait_max: string
    log_events: # Omit entirely if no logs exist in this bucket
      - time: string (HH:MM:SS)
        level: string
        message: string (Masked)
        occurrences: int

Ignored_Buckets: "X intervals omitted. System operated within hardware baselines with zero ERROR/WARN logs."
```

---

## 6. Docker Infrastructure Context

The core services supporting the assistant run via Docker Compose on the host. 

```yaml
services:
  # Voice to Text (CPU Optimized)
  whisper:
    image: ghcr.io/speaches-ai/speaches:latest-cpu
    container_name: whisper-api
    restart: unless-stopped
    ports:
      - "8001:8000"
    volumes:
      - /home/nick/docker/whisper/models:/home/ubuntu/.cache/huggingface/hub

  # LLM Observability & Tracing
  langfuse:
    image: ghcr.io/langfuse/langfuse:2
    container_name: langfuse
    restart: unless-stopped
    ports:
      - "${PORT}:3000"
    environment:
      - TZ=Europe/Athens
      - NODE_ENV=production
      - NEXTAUTH_URL=[http://192.168.1.120](http://192.168.1.120):${PORT}
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
      - SALT=${SALT}
      - TELEMETRY_ENABLED=${TELEMETRY_ENABLED}
      - DATABASE_URL=${DATABASE_URL}

  # RAG Vector Database
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    restart: unless-stopped
    ports:
      - "6333:6333" # REST API
    environment:
      - QDRANT__SERVICE__API_KEY=${QDRANT_API_KEY}
    volumes:
      - /home/nick/docker/qdrant:/qdrant/storage
```

---

## 7. Python Project Structure

```text
homelab_assistant/
├── pyproject.toml              # Dependency management strictly via `uv`
├── .env                        # API Keys, Tokens, IPs
├── scripts/
│   ├── check_anomalies.py      # Frequent anomaly cron job (Entry Point 1)
│   ├── daily_digest.py         # Morning CIO digest cron job (Entry Point 2)
│   └── ingest_docs.py          # Script to chunk & embed runbooks into Qdrant via Ollama
├── src/
│   ├── main.py                 # Telegram bot daemon (Entry Point 3)
│   ├── config/
│   │   └── settings.py         # Pydantic BaseSettings for env vars
│   ├── clients/                # Raw API Wrappers
│   │   ├── influxdb.py         
│   │   └── grafana_loki.py     
│   ├── bot/                    
│   │   └── telegram_app.py     # Bot daemon and push notification logic
│   └── agent/                  
│       ├── graph.py            # LangGraph Agent logic
│       ├── state.py            # TypedDict definition (inc. LangGraph internals)
│       ├── prompts.py          # Centralized System Prompts
│       ├── qdrant.py           # Vector DB tool (retrieves from 'homelab_assistant' collection)
│       ├── truenas.py          # TrueNAS Tool
│       └── tools.py            # Contains ping() and fused telemetry() aggregation logic
```