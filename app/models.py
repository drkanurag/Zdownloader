from typing import Optional, List
from pydantic import BaseModel, Field, field_validator

class FormatOption(BaseModel):
    format_id: str
    label: str
    resolution: Optional[str] = None
    height: Optional[int] = None
    fps: Optional[int] = None
    ext: str = "mp4"
    filesize: Optional[int] = None
    filesize_str: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    is_audio_only: bool = False
    needs_merge: bool = False

class AnalyzedLink(BaseModel):
    id: str
    url: str
    status: str = "supported"  # supported, direct_file, unsupported, drm_protected, error
    title: str = "Untitled Media"
    duration: Optional[int] = None
    duration_str: Optional[str] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    platform: str = "Web"
    formats: List[FormatOption] = Field(default_factory=list)
    selected_format_id: str = "best"
    error_message: Optional[str] = None

class AnalyzeBatchRequest(BaseModel):
    urls: List[str]

class EnqueueItem(BaseModel):
    url: str
    title: Optional[str] = None
    format_id: str = "best"
    format_label: Optional[str] = None
    thumbnail: Optional[str] = None
    platform: Optional[str] = None

class EnqueueDownloadsRequest(BaseModel):
    items: List[EnqueueItem]

class DownloadJob(BaseModel):
    id: str
    url: str
    title: str
    thumbnail: Optional[str] = None
    platform: str = "Web"
    format_id: str = "best"
    format_label: str = "Original Quality"
    status: str = "queued"  # queued, downloading, merging, completed, cancelled, error
    progress_percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed_bytes_sec: Optional[float] = None
    speed_str: str = ""
    eta_seconds: Optional[int] = None
    eta_str: str = ""
    download_dir: str = ""
    target_filepath: Optional[str] = None
    filename: Optional[str] = None
    error_message: Optional[str] = None
    created_at: float = 0.0
    completed_at: Optional[float] = None

    @field_validator("total_bytes", "downloaded_bytes", mode="before")
    @classmethod
    def cast_bytes_to_int(cls, v):
        if v is not None:
            try:
                return int(float(v))
            except Exception:
                return None
        return None

class SettingsUpdateRequest(BaseModel):
    download_dir: Optional[str] = None
    max_concurrent_downloads: Optional[int] = None
    default_quality: Optional[str] = None

