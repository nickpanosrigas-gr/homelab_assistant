# Home Lab AIOps Assistant: Master Architecture & Implementation Specification

This document serves as the complete architectural blueprint and technical specification for building a Python-based, LangGraph-orchestrated AIOps assistant for a Proxmox home lab. 

---

## 1. Core Constraints & Environmental Realities

* **Cloud Reasoning / High Availability:** The core reasoning LLM is **Gemini 3.1 Flash Lite**, ensuring fast inference, large context windows, and continuous uptime regardless of local hardware states.
* **The "Gaming Override" (Embeddings Only):** The local Ollama LXC (ID: 220) using a dynamically passed Nvidia RTX 2070 Super is strictly dedicated to generating vector embeddings (`nomic-embed-text`) for the local knowledge base. When the Windows 11 Gaming VM (ID: 130) starts, Ollama is shut down to reclaim the GPU. During this time, the assistant remains fully functional for querying and troubleshooting, though new documentation cannot be embedded until the GPU is released.
* **Safety Principle:** The assistant is strictly **read-only**. It will not execute state-changing infrastructure commands.

---

## 2. Technology Stack

* **Language:** Python 3.11+
* **Dependency Management:** `uv` (the modern, extremely fast standard for Python project management).
* **AI Orchestration:** LangChain and LangGraph (Unified ReAct Agent pattern).
* **LLM Backend:** Gemini 3.1 Flash Lite.
* **Vector Embeddings:** Local Ollama API `nomic-embed-text` (768 dimensions).
* **Vector Database:** Qdrant (Knowledge retrieval via Hybrid Search).
* **LLM Observability:** Langfuse (Tracing, metrics, and prompt management).
* **Voice-to-Text:** Speaches (CPU-based Whisper inference) running on the Linux Docker Host.
* **Telemetry Sources:** InfluxDB (Hardware Metrics) and Loki (Application Logs).
* **User Interface:** Telegram Bot API (supports text, voice memos, and proactive alerts).

---

## 3. System Architecture & Tooling

The assistant uses a **Unified Agent Model** powered by LangGraph. The agent dynamically accesses a centralized suite of specialized tools located in `src/agent/tools.py`, which route to deterministic functions in `src/tools/`.

### Core Tool Suite

| Tool | Role & Responsibility |
| :--- | :--- |
| `ping(service_name)` | **Connectivity Tester.** Executes a quick ICMP/HTTP check against known internal endpoints to verify basic uptime. |
| `telemetry(service_name, timeframe)` | **The Fused Telemetry Aggregator.** Queries Loki and InfluxDB in parallel. Calculates dynamic baselines, deduplicates logs, and outputs a highly compressed, time-aligned YAML matrix for the LLM. |
| `truenas(timeframe)` | **Storage API Client.** Direct interaction with the TrueNAS REST API to pull zpool health, dataset capacities, disk temperatures, and alert statuses. |
| `qdrant(query, ...filters)` | **Hybrid Search RAG Engine.** Queries the `homelab_assistant` collection. Combines semantic vector search with exact-match metadata filtering (e.g., `resource_id`, `domain`, `service_name`) to eliminate hallucinations. |

---

## 4. Knowledge Base Ingestion Strategy (RAG)

To maximize the efficiency of Gemini's context window and eliminate retrieval hallucinations, the documentation is stored using a **Markdown with YAML Frontmatter** strategy.

### Workflow
1. Monolithic documentation is broken into smaller, service-specific files stored in the `/data` directory (e.g., `vm-130-windows.md`, `docker-observability-stack.md`).
2. Each file begins with a strict YAML frontmatter block defining exact-match Qdrant Tag Keys (Metadata).
3. The `scripts/ingest_docs.py` script utilizes `python-frontmatter` to extract the metadata, and LangChain's `MarkdownHeaderTextSplitter` to chunk the documentation by `##` and `###` headers.
4. The cohesive chunks are vectorized by Ollama and uploaded to Qdrant, merging the YAML filters with the header context.

**Example Documentation Format:**
```markdown
---
domain: "docker_stack"
resource_id: 120
content_type: "docker_compose"
service_names: 
  - "grafana"
  - "loki"
ip_address: "192.168.1.120"
hardware_dependencies: []
---

### Grafana & Observability Stack
[Markdown text and docker compose yaml goes here...]
```

---

## 5. Core Workflows

### 5.1 Proactive Anomaly Detection (Frequent Cron Job)
1.  **Telemetry Aggregation:** Calls the `telemetry` tool.
2.  **Logic Gate:** Filters out baseline/normal behavior. If the resulting matrix is empty, the script exits cleanly.
3.  **LLM Analysis:** If anomalies exist, the YAML payload is passed to Gemini. The AI references the `qdrant` tool for context on the failing service.
4.  **Notification:** The AI summarizes the cause and sends a **Telegram Alert**.

### 5.2 Interactive Querying (Telegram Bot Daemon)
1.  User sends a text or voice message. Voice is transcribed by the local Speaches container.
2.  Message enters the LangGraph `State`.
3.  **Agent Analysis:** Gemini analyzes the request, triggers Hybrid Search via `qdrant` for configuration specifics, and uses `telemetry`, `ping`, or `truenas` for live data.
4.  **Response:** The Agent synthesizes the data and replies in the Telegram chat (with automatic markdown-to-mobile formatting), while traces are logged to Langfuse.

---

## 6. Fused Telemetry Aggregator Specification

The `telemetry` tool strictly enforces LLM token efficiency, outputting a time-aligned YAML schema. If a bucket is entirely normal, it is omitted.

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
    infrastructure_anomalies: 
      CPU_max: string
      Disk_IO_Wait_max: string
    log_events: 
      - time: string (HH:MM:SS)
        level: string
        message: string (Masked)
        occurrences: int

Ignored_Buckets: "X intervals omitted. System operated within hardware baselines with zero ERROR/WARN logs."
```

---

## 7. Docker Infrastructure Context

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

## 8. Python Project Structure

```text
homelab_assistant/
├── pyproject.toml              # Dependency management strictly via `uv`
├── .env                        # API Keys, Tokens, IPs
├── data/                       # Markdown files w/ YAML frontmatter for RAG
├── scripts/
│   ├── check_anomalies.py      # Frequent anomaly cron job (Entry Point 1)
│   ├── daily_digest.py         # Morning CIO digest cron job (Entry Point 2)
│   └── ingest_docs.py          # Extracts frontmatter & embeds docs into Qdrant
├── src/
│   ├── main.py                 # Telegram bot daemon (Entry Point 3)
│   ├── config/
│   │   └── settings.py         # Pydantic BaseSettings for env vars
│   ├── bot/                    
│   │   ├── telegram_app.py     # Bot daemon, push notifications, markdown formatting
│   │   └── whisper_stt.py      # Audio transcription routing
│   ├── tools/                  # Raw deterministic tool logic
│   │   ├── ping.py             
│   │   ├── telemetry.py        # Fused Loki/InfluxDB aggregator
│   │   ├── truenas.py          # TrueNAS API integration
│   │   └── qdrant.py           # Qdrant Hybrid Search execution
│   └── agent/                  
│       ├── graph.py            # LangGraph StateGraph & LLM instantiation
│       ├── state.py            # TypedDict definition (inc. LangGraph internals)
│       └── tools.py            # The @tool wrappers exposing functions to Gemini
```