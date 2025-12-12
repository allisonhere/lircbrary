import asyncio
import shutil
import uuid
import logging
from pathlib import Path
from typing import Optional

from redis import Redis
from rq import Queue

from .config import get_settings
from .config_store import load_config
from .irc_client import IrcClient, IrcDownloadError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    logger.info(f"Starting download job for result_id: {result_id}")
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
    
    # Check if result_id looks like a filename with an extension
    # result_id might be "!BotName Filename.epub"
    extension = ".zip"
    is_ebook = False
    
    # Try to clean up the filename from the trigger command
    clean_name = result_id
    if result_id.startswith("!"):
        # Remove "!BotName " prefix
        parts = result_id.split(" ", 1)
        if len(parts) > 1:
            clean_name = parts[1].strip()
    
    # Check for extensions
    lower_name = clean_name.lower()
    if lower_name.endswith(".epub"):
        extension = ".epub"
        is_ebook = True
    elif lower_name.endswith(".mobi"):
        extension = ".mobi"
        is_ebook = True
    elif lower_name.endswith(".azw3"):
        extension = ".azw3"
        is_ebook = True
    elif lower_name.endswith(".pdf"):
        extension = ".pdf"
        is_ebook = True

    dest_file = download_dir / f"{clean_name if is_ebook else result_id}-{job_id}{extension}"
    logger.info(f"Downloading to: {dest_file}")

    # irc.download_pack may be async; run it in a temporary event loop
    downloaded_path = asyncio.run(irc.download_pack(result_id, bot, dest_file))  # type: ignore[arg-type]
    if not isinstance(downloaded_path, Path):
        logger.error(f"Unexpected download type: {type(downloaded_path)}")
        raise IrcDownloadError(f"Unexpected download type: {type(downloaded_path)}")

    if not downloaded_path.exists() or downloaded_path.stat().st_size == 0:
        logger.error("Downloaded file is empty or missing")
        # Cleanup empty file artifact
        if downloaded_path.exists():
            downloaded_path.unlink()
        raise IrcDownloadError("Downloaded file is empty or missing")

    logger.info(f"Download successful. Size: {downloaded_path.stat().st_size} bytes")

    # Post-download: Check if the file is actually an EPUB (even if named .zip)
    # EPUBs are ZIPs that contain a 'mimetype' file.
    is_actual_epub = False
    import zipfile
    if zipfile.is_zipfile(downloaded_path):
        try:
            with zipfile.ZipFile(downloaded_path, 'r') as zf:
                # Check for mimetype file which is required for valid EPUBs
                if 'mimetype' in zf.namelist():
                    with zf.open('mimetype') as f:
                        content = f.read().decode('utf-8', errors='ignore').strip()
                        if content == 'application/epub+zip':
                            is_actual_epub = True
                            logger.info("Detected EPUB mimetype in zip file")
        except Exception as e:
            logger.warning(f"Zip check failed: {e}")

    if is_ebook or is_actual_epub:
        # Ensure it has the correct extension if we detected it by content
        final_source = downloaded_path
        if is_actual_epub and downloaded_path.suffix.lower() != ".epub":
            new_path = downloaded_path.with_suffix(".epub")
            logger.info(f"Renaming {downloaded_path} to {new_path}")
            downloaded_path.rename(new_path)
            final_source = new_path
            
        # It's the book, don't extract.
        final_path = library_dir / final_source.name
        logger.info(f"Moving file to library: {final_path}")
        shutil.move(str(final_source), final_path)
        logger.info("Task complete.")
        return str(final_path)

    logger.info(f"Extracting archive: {archive_path}")
    archive_path = downloaded_path
    try:
        extracted_dir = _safe_extract(archive_path, temp_dir)
    except shutil.ReadError:
        # Not an archive (likely the placeholder mock); move directly into library.
        logger.warning("Not a valid archive, moving directly to library")
        final_path = library_dir / archive_path.name
        shutil.move(str(archive_path), final_path)
        return str(final_path)

    # simple heuristic: choose first file that looks like an ebook
    candidates = sorted(
        [p for p in extracted_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".epub", ".pdf", ".mobi", ".azw3", ".txt"}]
    )
    chosen = candidates[0] if candidates else next(iter(extracted_dir.rglob("*")), None)
    if not chosen:
        logger.error("No files found in archive")
        raise IrcDownloadError("No files found in archive")

    final_path = library_dir / chosen.name
    logger.info(f"Moved extracted file to: {final_path}")
    shutil.move(str(chosen), final_path)
    return str(final_path)
