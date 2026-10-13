import time
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

class BaseEvent(BaseModel):
    event_id: str
    event_type: str
    timestamp: float = Field(default_factory=time.time)

class JobCreatedEvent(BaseEvent):
    job_id: str
    url: str
    title: str

class JobProgressEvent(BaseEvent):
    job_id: str
    status: str
    progress_percent: float
    downloaded_bytes: int
    total_bytes: Optional[int] = None
    speed_str: str = ""
    eta_str: str = ""

class JobCompletedEvent(BaseEvent):
    job_id: str
    filepath: str
    filename: str
    total_bytes: int

class JobFailedEvent(BaseEvent):
    job_id: str
    error_message: str

class JobCancelledEvent(BaseEvent):
    job_id: str

