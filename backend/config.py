import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Load env from project root or backend/.env
root_env = Path(__file__).resolve().parents[1] / ".env"
backend_env = Path(__file__).resolve().parent / ".env"
load_dotenv(root_env)
load_dotenv(backend_env)

@dataclass
class Settings:
    database_url: str
    deepseek_api_key: str
    deepseek_base_url: str
    default_timezone: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5434/ai_pulse"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "Asia/Taipei"),
    )
