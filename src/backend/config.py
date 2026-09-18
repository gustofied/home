from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BACKEND_")

    app_name: str = "DataBank Explorer"
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = True
    frontend_dir: Path = Path(__file__).resolve().parents[2] / "frontend"
    data_dir: Path = Path(__file__).resolve().parents[2] / "data"


settings = Settings()
