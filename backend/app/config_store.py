import json
from pathlib import Path
from typing import Optional

from .config import get_settings
from .schemas import ConfigData, Theme


def _config_path() -> Path:
    settings = get_settings()
    return Path(settings.config_file)


def load_config() -> ConfigData:
    path = _config_path()
    settings = get_settings()
    defaults = ConfigData(
        download_dir=str(settings.download_dir),
        library_dir=str(settings.library_dir),
        temp_dir=str(settings.temp_dir),
        max_download_bytes=None,
        allowed_bots=[],
        irc_server=settings.irc_server,
        irc_port=settings.irc_port,
        irc_ssl=settings.irc_ssl,
        irc_ssl_verify=settings.irc_ssl_verify,
        irc_channel=settings.irc_channel,
        irc_nick=settings.irc_nick,
        irc_realname=settings.irc_realname,
        theme=Theme.light,
    )
    if not path.exists():
        return defaults
    try:
        raw = json.loads(path.read_text())
        return ConfigData(**{**defaults.dict(), **raw})
    except Exception:
        return defaults


def save_config(data: ConfigData) -> ConfigData:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.model_dump_json(indent=2))
    return data
