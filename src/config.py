from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Model settings
    model_name: str = "facebook/opt-125m"
    max_new_tokens: int = 100
    
    # Batching settings
    max_batch_size: int = 8
    batch_timeout_ms: float = 50.0
    
    # Cache settings
    cache_backend: str = "memory"
    cache_ttl_seconds: int = 300
    cache_max_entries: int = 1000
    redis_url: str = "redis://localhost:6379"
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    
    class Config:
        env_file = ".env"

settings = Settings()
