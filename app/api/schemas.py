import time
from typing import Generic, TypeVar, Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.domain.models import AnalyzedLink, DownloadJob, FormatOption

T = TypeVar("T")

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[ErrorDetail] = None
    timestamp: float = Field(default_factory=time.time)

class AnalyzeBatchRequest(BaseModel):
    urls: List[str]

class EnqueueItemDto(BaseModel):
    url: str
    title: Optional[str] = None
    format_id: str = "best"
    format_label: Optional[str] = None
    thumbnail: Optional[str] = None
    platform: Optional[str] = None
    priority: int = 5

class EnqueueDownloadsRequest(BaseModel):
    items: List[EnqueueItemDto]

class SettingsUpdateRequest(BaseModel):
    download_dir: Optional[str] = None
    max_concurrent_downloads: Optional[int] = None
    auto_clear_completed: Optional[bool] = None
    default_quality: Optional[str] = None

