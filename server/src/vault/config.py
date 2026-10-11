from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VAULT_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    embed_model: str = "clip-b32"  # "none" turns embeddings off (search falls back to text only)
    embed_precision: str = "fp32"  # fp32 | int8 (smaller and faster, slightly less accurate)
    autotag_top_k: int = 5
    autotag_min_prob: float = 0.02
    max_upload_bytes: int = 50 * 1024 * 1024
    near_dup_cosine: float = 0.94
    near_dup_phash: int = 6
    auth_disabled: bool = False
    worker_enabled: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vault.db"

    @property
    def blobs_dir(self) -> Path:
        return self.data_dir / "blobs"

    @property
    def derived_dir(self) -> Path:
        return self.data_dir / "derived"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.blobs_dir, self.derived_dir, self.models_dir, self.staging_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
