from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_PKG_ROOT = Path(__file__).resolve().parent
_LOADED_ENV: Path | None = None


def _load_env_files() -> None:
    global _LOADED_ENV
    candidates = (
        _PKG_ROOT / ".env",
        _PKG_ROOT.parent / "wb_advert_probe" / ".env",
    )
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=True)
            _LOADED_ENV = path
            return


_load_env_files()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_PKG_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    wb_api_token: str = ""
    database_url: str = ""
    sync_interval_min: int = 15
    request_pause_sec: float = 2.0
    pilot_config_path: str = "../data/pilot/config.yaml"
    pilot_data_path: str = "../data/pilot"

    promotion_base: str = "https://advert-api.wildberries.ru"
    analytics_base: str = "https://seller-analytics-api.wildberries.ru"
    marketplace_base: str = "https://marketplace-api.wildberries.ru"


settings = Settings()


def require_token() -> str:
    token = (settings.wb_api_token or "").strip()
    if not token:
        raise SystemExit(
            "WB_API_TOKEN not set.\n"
            f"  Create {_PKG_ROOT / '.env'} with WB_API_TOKEN=...\n"
            f"  Or use {_PKG_ROOT.parent / 'wb_advert_probe' / '.env'}"
        )
    return token


def env_file_used() -> Path | None:
    return _LOADED_ENV
