from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Local AI Endpoints
    OLLAMA_BASE_URL: str
    WHISPER_API_URL: str
    
    # Telemetry Endpoints
    PROMETHEUS_URL: str
    LOKI_URL: str
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    TELEGRAM_ALLOWED_USER_ID: int # Crucial for home lab security
    
    # Read from the .env file in the root directory
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()