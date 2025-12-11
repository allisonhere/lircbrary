import asyncio
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from rq import Queue
from rq.job import Job

from .config import Settings, get_settings
from .config_store import load_config, save_config
from .irc_client import IrcClient
from .irc_log import get_logs
from .irc_session import session
from .irc_ping import tcp_probe
from .schemas import (
    ConfigData,
    DownloadRequest,
    DownloadResponse,
    Health,
    IrcLog,
    JobInfo,
    JobStatus,
    SearchRequest,
    SearchResponse,
)
from .tasks import download_and_process, get_queue


def create_app(settings: Settings = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=Health)
    async def health() -> Health:
        try:
            redis_ok = Redis.from_url(settings.redis_url).ping()
        except Exception:
            redis_ok = False
        return Health(status="ok", redis=bool(redis_ok))

    @app.get("/config", response_model=ConfigData)
    async def get_config() -> ConfigData:
        return load_config()

    @app.post("/config", response_model=ConfigData)
    async def update_config(cfg: ConfigData) -> ConfigData:
        return save_config(cfg)

    @app.get("/irc-log", response_model=IrcLog)
    async def irc_log() -> IrcLog:
        return IrcLog(lines=get_logs())

    @app.post("/irc-log/clear")
    async def irc_log_clear():
        from .irc_log import clear_logs

        clear_logs()
        return {"status": "cleared"}

    @app.get("/irc/ping")
    async def irc_ping(host: str, port: int):
        ok, detail = tcp_probe(host, port)
        return {"ok": ok, "detail": detail}

    @app.post("/irc/connect")
    async def irc_connect():
        session.connect()
        return {"status": "connecting"}

    @app.post("/irc/disconnect")
    async def irc_disconnect():
        session.disconnect()
        return {"status": "disconnected"}

    @app.get("/irc/status")
    async def irc_status():
        return session.status()

    @app.post("/search", response_model=SearchResponse)
    async def search(req: SearchRequest) -> SearchResponse:
        client = IrcClient()
        try:
            results = await client.search(req.query, req.author)
        except Exception as e:
            # Surface error so UI can display it
            raise HTTPException(status_code=500, detail=str(e))
        return SearchResponse(results=results)

    @app.post("/download", response_model=DownloadResponse)
    async def download(req: DownloadRequest, queue: Queue = Depends(get_queue)) -> DownloadResponse:
        job = queue.enqueue(download_and_process, req.result_id, req.bot, req.target_folder)
        return DownloadResponse(job_id=job.id)

    @app.get("/jobs/{job_id}", response_model=JobInfo)
    async def job_status(job_id: str, queue: Queue = Depends(get_queue)) -> JobInfo:
        job = Job.fetch(job_id, connection=queue.connection)
        status_map = {
            "queued": JobStatus.queued,
            "started": JobStatus.started,
            "finished": JobStatus.finished,
            "failed": JobStatus.failed,
        }
        status = status_map.get(job.get_status(), JobStatus.failed)
        return JobInfo(
            id=job.id,
            status=status,
            enqueued_at=job.enqueued_at,
            started_at=job.started_at,
            ended_at=job.ended_at,
            error=str(job.exc_info) if job.is_failed else None,
            result_path=str(job.result) if job.result else None,
        )

    return app


app = create_app()
