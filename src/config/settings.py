from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Local AI Endpoints
    OLLAMA_BASE_URL: str
    OLLAMA_MODEL: str
    OLLAMA_NUM_CTX: int
    OLLAMA_TEMPERATURE: float
    
    # Whisper
    WHISPER_API_URL: str
    WHISPER_MODEL: str
    
    # Telemetry Endpoints
    INFLUXDB_URL: str
    INFLUXDB_TOKEN: str
    INFLUXDB_ORG: str
    INFLUXDB_PROXMOX_BUCKET: str
    INFLUXDB_DOCKER_BUCKET: str
    LOKI_URL: str
    
    # Infrastructure - TrueNAS
    TRUENAS_URL: str
    TRUENAS_API_KEY: str
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ALLOWED_USER_ID: int
    
    # Read from the .env file in the root directory
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Instantiate settings to be imported across the project
settings = Settings()