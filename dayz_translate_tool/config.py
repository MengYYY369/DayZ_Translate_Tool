import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    ai_backend: str = "google"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = ""
    timeout_seconds: int = 60
    opencode_path: str = "opencode"
    opencode_args: str = ""
    autosave_every: int = 5
    max_workers: int = 3
    rate_limit_seconds: float = 1.0
    target_columns: list[str] | None = None
    glossary_entries: list[dict[str, str]] = field(default_factory=list)
    last_csv_path: str = ""


def default_config_path() -> Path:
    return Path.home() / ".dayz_translate_tool.json"


def load_config(path: Path | None = None) -> AppConfig:
    target = path or default_config_path()
    if not target.exists():
        return AppConfig()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppConfig()
    config = AppConfig()
    for key, value in data.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config


def save_config(config: AppConfig, path: Path | None = None) -> None:
    target = path or default_config_path()
    target.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
