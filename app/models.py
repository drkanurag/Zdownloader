"""
DEPRECATED: app.models has been refactored to app.domain.models and app.api.schemas.
This module provides backward-compatible re-exports for existing consumers and test suites.
"""
import warnings

warnings.warn(
    "app.models is deprecated; use app.domain.models instead.",
    DeprecationWarning,
    stacklevel=2
)

from app.domain.models import (
    JobStatus,
    JobPriority,
    FormatOption,
    AnalyzedLink,
    DownloadJob,
)
from app.api.schemas import (
    AnalyzeBatchRequest,
    EnqueueItemDto as EnqueueItem,
    EnqueueDownloadsRequest,
)

__all__ = [
    "JobStatus",
    "JobPriority",
    "FormatOption",
    "AnalyzedLink",
    "DownloadJob",
    "AnalyzeBatchRequest",
    "EnqueueItem",
    "EnqueueDownloadsRequest",
]
