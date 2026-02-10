"""App configuration."""
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/belegsync.db"
    secret_key: str = "change-me-in-production"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b-instruct-q4_K_M"
    ocr_language: str = "deu"
    max_upload_size_mb: int = 50
    maesn_api_key: str = ""
    maesn_api_url: str = "https://api.maesn.com/v1"
    maesn_sandbox: bool = True
    upload_dir: str = "./uploads"

    class Config:
        env_file = ".env"

settings = Settings()
