from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = Field("lircbrary", description="Service name")
    server_host: str = Field("0.0.0.0", description="API host")
    server_port: int = Field(8000, description="API port")

    irc_server: str = Field("irc.highway.net", description="IRC server hostname")
    irc_port: int = Field(6667, description="IRC server port")
    irc_ssl: bool = Field(False, description="Use SSL/TLS for IRC connection")
    irc_ssl_verify: bool = Field(True, description="Verify SSL certificates for IRC")
    irc_channel: str = Field("#ebooks", description="Channel to join")
    irc_nick: str = Field("lircbrarybot", description="Nickname to use")
    irc_realname: str = Field("lircbrary", description="Real name for IRC registration")

    download_dir: Path = Field(Path("/data/downloads"), description="Where raw downloads are saved")
    library_dir: Path = Field(Path("/data/library"), description="Where extracted ebooks are stored")
    temp_dir: Path = Field(Path("/home/allie/temp"), description="Scratch directory for zips")
    config_file: Path = Field(Path("/data/config.json"), description="Path to persisted config")

    redis_url: str = Field("redis://redis:6379/0", description="Redis connection URL")
    queue_name: str = Field("lircbrary-jobs", description="RQ queue name")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
