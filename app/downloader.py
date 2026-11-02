"""
DEPRECATED: app.downloader has been refactored to app.services.download_service.
This module provides backward-compatible wrappers delegating to DownloadService.
"""
import warnings
from typing import Callable, Optional, Any
from app.domain.models import DownloadJob
from app.domain.exceptions import DownloadCancelledException
from app.services.download_service import DownloadService, download_service

warnings.warn(
    "app.downloader is deprecated; use app.services.download_service instead.",
    DeprecationWarning,
    stacklevel=2
)

async def download_direct_file(
    job: DownloadJob,
    on_progress: Optional[Callable[[DownloadJob], Any]] = None,
    check_cancelled: Optional[Callable[[], bool]] = None
) -> str:
    cancelled_fn = check_cancelled or (lambda: False)
    return await download_service.download_direct(job, check_cancelled=cancelled_fn)

async def download_ytdlp(
    job: DownloadJob,
    on_progress: Optional[Callable[[DownloadJob], Any]] = None,
    check_cancelled: Optional[Callable[[], bool]] = None
) -> str:
    cancelled_fn = check_cancelled or (lambda: False)
    return await download_service.download_ytdlp(job, check_cancelled=cancelled_fn)

__all__ = [
    "DownloadCancelledException",
    "download_direct_file",
    "download_ytdlp",
]
