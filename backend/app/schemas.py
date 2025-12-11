from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, HttpUrl


class JobStatus(str, Enum):
    queued = "queued"
    started = "started"
    finished = "finished"
    failed = "failed"


class Theme(str, Enum):
    light = "light"
    dark = "dark"


class SearchRequest(BaseModel):
    query: str
    author: Optional[str] = None


class SearchResult(BaseModel):
    id: str
    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    bot: Optional[str] = None
    size_bytes: Optional[int] = None


class DownloadRequest(BaseModel):
    result_id: str
    bot: Optional[str] = None
    target_folder: Optional[str] = None


class JobInfo(BaseModel):
    id: str
    status: JobStatus
    enqueued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    result_path: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[SearchResult]


class DownloadResponse(BaseModel):
    job_id: str


class Health(BaseModel):
    status: str
    redis: bool


class ConfigData(BaseModel):
    download_dir: str
    library_dir: str
    temp_dir: str
    max_download_bytes: Optional[int] = None
    allowed_bots: List[str] = []
    irc_server: Optional[str] = None
    irc_port: Optional[int] = None
    irc_ssl: Optional[bool] = None
    irc_ssl_verify: Optional[bool] = None
    irc_channel: Optional[str] = None
    irc_nick: Optional[str] = None
    irc_realname: Optional[str] = None
    theme: Theme = Theme.light


class IrcLog(BaseModel):
    lines: List[str]
