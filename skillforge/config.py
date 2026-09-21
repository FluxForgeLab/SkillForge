"""Application settings. Business code reads configuration only through get_settings()."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelAdapterName = Literal["fake", "openai_compatible", "stepfun_local", "stepfun_api"]
DemoMode = Literal["replay", "live"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SKILLFORGE_",
        extra="ignore",
        protected_namespaces=(),
    )

    data_dir: Path = Path("data")
    sqlite_path: Path = Path("data/skillforge.db")

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173"]

    model_adapter: ModelAdapterName = "fake"
    model_base_url: str = "http://127.0.0.1:8080/v1"
    model_api_key: SecretStr = SecretStr("")
    model_name: str = "step-3.7-flash"

    max_steps: int = 20
    max_seconds: int = 120
    temperature: float = 0.0
    seed: int | None = None
    structured_output_max_retries: int = 3

    demo_mode: DemoMode = "replay"
    opslab_project: str = "skillforge-lab"
    opslab_base_url: str = "http://127.0.0.1:8088"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
