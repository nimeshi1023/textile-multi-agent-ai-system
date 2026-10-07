from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str = (
        "postgresql+psycopg2://user:pass@localhost:5432/FabricFlow"
    )

    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.8-flash"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

print(f"Environment file: {ENV_FILE}")
print(f"Environment file exists: {ENV_FILE.exists()}")
print(f"Gemini API key loaded: {bool(settings.GEMINI_API_KEY)}")
print(f"Gemini model: {settings.GEMINI_MODEL}")