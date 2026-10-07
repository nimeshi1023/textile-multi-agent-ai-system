from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str = (
        "postgresql+psycopg2://user:pass@localhost:5432/FabricFlow"
    )

    GROQ_API_KEY: str
    GROQ_MODEL: str = "openai/gpt-oss-120b"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

print(f"Environment file: {ENV_FILE}")
print(f"Environment file exists: {ENV_FILE.exists()}")
print(f"Groq API key loaded: {bool(settings.GROQ_API_KEY)}")
print(f"Groq model: {settings.GROQ_MODEL}")