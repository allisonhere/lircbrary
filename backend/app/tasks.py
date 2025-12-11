import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Optional

from redis import Redis
from rq import Queue

from .config import get_settings
from .config_store import load_config
from .irc_client import IrcClient, IrcDownloadError


def get_queue() -> Queue:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url)
    return Queue(settings.queue_name, connection=redis)


def _safe_extract(archive_path: Path, target_dir: Path) -> Path:
    """
    Extracts zip-like archives into target_dir/<job_id>. Attempts to avoid
    directory traversal by enforcing resolved paths under the target root.
    """
    job_dir = target_dir / archive_path.stem
    job_dir.mkdir(parents=True, exist_ok=True)
    shutil.unpack_archive(str(archive_path), str(job_dir))
    for child in job_dir.rglob("*"):
        if not child.resolve().is_relative_to(job_dir.resolve()):
            raise ValueError(f"Invalid archive entry: {child}")
    return job_dir


def download_and_process(result_id: str, bot: Optional[str] = None, target_folder: Optional[str] = None) -> str:
    """
    RQ job: request a pack, download, extract, and place best guess into library.
    Returns the final file path as string.
    """
    settings = get_settings()
    cfg = load_config()
    irc = IrcClient()

    download_dir = Path(cfg.download_dir or settings.download_dir)
    library_dir = Path(target_folder) if target_folder else Path(cfg.library_dir or settings.library_dir)
    temp_dir = Path(cfg.temp_dir or settings.temp_dir)

    download_dir.mkdir(parents=True, exist_ok=True)
    library_dir.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    dest_zip = download_dir / f"{result_id}-{job_id}.zip"

    # irc.download_pack may be async; run it in a temporary event loop
    downloaded_path = asyncio.run(irc.download_pack(result_id, bot, dest_zip))  # type: ignore[arg-type]
    if not isinstance(downloaded_path, Path):
        raise IrcDownloadError(f"Unexpected download type: {type(downloaded_path)}")

    archive_path = downloaded_path
    try:
        extracted_dir = _safe_extract(archive_path, temp_dir)
    except shutil.ReadError:
        # Not an archive (likely the placeholder mock); move directly into library.
        final_path = library_dir / archive_path.name
        shutil.move(str(archive_path), final_path)
        return str(final_path)

    # simple heuristic: choose first file that looks like an ebook
    candidates = sorted(
        [p for p in extracted_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".epub", ".pdf", ".mobi", ".azw3", ".txt"}]
    )
    chosen = candidates[0] if candidates else next(iter(extracted_dir.rglob("*")), None)
    if not chosen:
        raise IrcDownloadError("No files found in archive")

    final_path = library_dir / chosen.name
    shutil.move(str(chosen), final_path)
    return str(final_path)
