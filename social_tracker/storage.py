from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
APP_DATA_DIR = BASE_DIR / "app_data"
CONFIG_PATH = APP_DATA_DIR / "monitor_config.json"
SNAPSHOT_PATH = APP_DATA_DIR / "snapshots.json"


DEFAULT_CONFIG: dict[str, Any] = {
    "target_name": "Serenity",
    "aliases": ["Serenity", "@aleabitoreddit", "aleabitoreddit"],
    "x_profiles": ["aleabitoreddit"],
    "x_status_urls": [],
    "reddit_users": [],
    "web_urls": [],
    "search_queries": [
        'site:x.com/aleabitoreddit "my positions"',
        'site:x.com/aleabitoreddit bought OR "my long"',
        'site:reddit.com aleabitoreddit holdings OR portfolio',
    ],
    "post_limit": 8,
    "llm": {
        "enabled": False,
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
}


def ensure_app_data_dir() -> None:
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)


def ensure_runtime_files() -> None:
    ensure_app_data_dir()
    if not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text("[]\n", encoding="utf-8")


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return deepcopy(fallback)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return deepcopy(fallback)


def _write_json(path: Path, payload: Any) -> None:
    ensure_runtime_files()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_config() -> dict[str, Any]:
    ensure_runtime_files()
    config = _read_json(CONFIG_PATH, DEFAULT_CONFIG)
    merged = deepcopy(DEFAULT_CONFIG)
    merged.update(config)
    merged["llm"] = {**DEFAULT_CONFIG["llm"], **config.get("llm", {})}
    merged["llm"].pop("api_key", None)
    return merged


def save_config(config: dict[str, Any]) -> None:
    config = deepcopy(config)
    config.setdefault("llm", {}).pop("api_key", None)
    _write_json(CONFIG_PATH, config)


def load_snapshots() -> list[dict[str, Any]]:
    ensure_runtime_files()
    return _read_json(SNAPSHOT_PATH, [])


def append_snapshot(snapshot: dict[str, Any]) -> None:
    snapshots = load_snapshots()
    snapshots.append(snapshot)
    _write_json(SNAPSHOT_PATH, snapshots[-30:])


def resolve_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        import streamlit as st

        secret_value = st.secrets.get(name, "")
        if secret_value:
            return str(secret_value).strip()
    except Exception:
        pass
    return ""


def resolve_llm_config(llm_config: dict[str, Any]) -> dict[str, Any]:
    resolved = deepcopy(llm_config)
    api_key = (
        resolve_secret("DEEPSEEK_API_KEY")
        or resolve_secret("OPENAI_API_KEY")
        or resolve_secret("LLM_API_KEY")
    )
    resolved["api_key"] = api_key
    resolved["api_key_source"] = (
        "DEEPSEEK_API_KEY / OPENAI_API_KEY / LLM_API_KEY" if api_key else ""
    )
    return resolved
