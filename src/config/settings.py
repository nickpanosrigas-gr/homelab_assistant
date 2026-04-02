from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Local AI Endpoints
    OLLAMA_BASE_URL: str
    OLLAMA_MODEL: str
    WHISPER_API_URL: str
    
    # Telemetry Endpoints
    PROMETHEUS_URL: str
    LOKI_URL: str
    
    # TrueNAS
    TRUENAS_IP: str
    TRUENAS_API_KEY: str
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ALLOWED_USER_ID: int
    
    # Read from the .env file in the root directory
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()