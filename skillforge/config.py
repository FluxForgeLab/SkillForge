"""Application settings. Business code reads configuration only through get_settings()."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelAdapterName = Literal["fake", "openai_compatible", "stepfun_local", "stepfun_api"]
ModelProfileName = Literal["custom", "local_vllm", "kimi"]
DemoMode = Literal["replay", "live"]
RetrievalBackendName = Literal["sqlite_fts", "lancedb", "memory"]
RetrievalModeName = Literal["keyword", "vector", "hybrid"]
EmbedderName = Literal["null", "openai_compatible"]


@dataclass(frozen=True)
class ResolvedModel:
    """Model identity after applying model_profile. api_key is the raw secret."""

    adapter: ModelAdapterName
    base_url: str
    api_key: str
    name: str
    temperature: float


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
    cors_origins: list[str] = [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]

    model_adapter: ModelAdapterName = "fake"
    model_profile: ModelProfileName = "custom"
    model_base_url: str = "http://127.0.0.1:8080/v1"
    model_api_key: SecretStr = SecretStr("")
    model_name: str = "step-3.7-flash"
    model_local_base_url: str = "http://127.0.0.1:8001/v1"
    model_local_name: str = "nvidia/Qwen3.6-35B-A3B-NVFP4"
    model_kimi_base_url: str = "https://api.moonshot.cn/v1"
    model_kimi_name: str = "kimi-k3"
    model_timeout_seconds: float = 300.0
    transcript_path: str = ""

    max_steps: int = 20
    max_seconds: int = 120
    temperature: float = 0.0
    seed: int | None = None
    structured_output_max_retries: int = 3

    skills_generated_dir: Path = Path("skills/generated")
    skills_published_dir: Path = Path("skills/published")

    demo_mode: DemoMode = "replay"
    opslab_project: str = "skillforge-lab"
    opslab_base_url: str = "http://127.0.0.1:8088"
    opslab_nginx_conf: Path = Path("demo/ops-lab/nginx/nginx.conf")
    sandbox_image: str = "skillforge-sandbox:local"
    sandbox_backend: Literal["docker", "openshell"] = "docker"

    retrieval_backend: RetrievalBackendName = "sqlite_fts"
    retrieval_default_mode: RetrievalModeName = "keyword"
    index_dir: Path = Path("data/index")
    embedder: EmbedderName = "null"
    embedding_base_url: str = ""
    embedding_model: str = ""
    embedding_dimension: int | None = None

    def resolved_model(self) -> ResolvedModel:
        """Select local vLLM or Kimi without letting Kimi's temperature leak.

        custom keeps the raw fields, including temperature 0. local_vllm always
        uses temperature 0. kimi always uses temperature 1, which Moonshot
        requires. StepFun adapters stay unimplemented.
        """
        if self.model_profile == "local_vllm":
            return ResolvedModel(
                adapter="openai_compatible",
                base_url=self.model_local_base_url,
                api_key="",
                name=self.model_local_name,
                temperature=0.0,
            )
        if self.model_profile == "kimi":
            return ResolvedModel(
                adapter="openai_compatible",
                base_url=self.model_kimi_base_url,
                api_key=self.model_api_key.get_secret_value(),
                name=self.model_kimi_name,
                temperature=1.0,
            )
        return ResolvedModel(
            adapter=self.model_adapter,
            base_url=self.model_base_url,
            api_key=self.model_api_key.get_secret_value(),
            name=self.model_name,
            temperature=self.temperature,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
