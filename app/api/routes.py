import os
import asyncio
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from app.api.schemas import (
    ApiResponse,
    ErrorDetail,
    AnalyzeBatchRequest,
    EnqueueDownloadsRequest,
    SettingsUpdateRequest
)
from app.services.inspection_service import inspection_service
from app.services.scheduler_service import scheduler_service
from app.services.storage_service import storage_service
from app.api.websocket import ws_broadcaster
from app.utils import get_ffmpeg_path

router = APIRouter()

# -----------------------------------------------------------
# HEALTH PROBES (Microservices Standards)
# -----------------------------------------------------------
@router.get("/health", tags=["Health"])
@router.get("/health/live", tags=["Health"])
async def liveness_probe():
    """Liveness probe to confirm microservice container is up."""
    return {"status": "alive"}

@router.get("/ready", tags=["Health"])
@router.get("/health/ready", tags=["Health"])
async def readiness_probe():
    """Readiness probe verifying disk and FFmpeg availability."""
    ffmpeg_ready = get_ffmpeg_path() is not None
    disk_usage = storage_service.get_disk_usage()
    return {
        "status": "ready",
        "ffmpeg_ready": ffmpeg_ready,
        "storage_ready": os.path.exists(storage_service.base_dir),
        "disk": disk_usage
    }

# -----------------------------------------------------------
# STATUS & SETTINGS
# -----------------------------------------------------------
@router.get("/api/status", tags=["System"])
@router.get("/status", tags=["System"])
@router.get("/api", tags=["System"])
@router.get("/api/index.py", tags=["System"])
async def get_system_status():
    ffmpeg_bin = get_ffmpeg_path()
    return {
        "status": "online",
        "agent": "Zdownloader High-Performance Engine",
        "version": "2.0.0-microservices",
        "ffmpeg_available": ffmpeg_bin is not None,
        "ffmpeg_path": ffmpeg_bin,
        "download_dir": scheduler_service.settings.download_dir,
        "max_concurrent_downloads": scheduler_service.settings.max_concurrent_downloads,
        "auto_clear_completed": scheduler_service.settings.auto_clear_completed,
        "default_quality": scheduler_service.settings.default_quality
    }

@router.get("/api/settings", tags=["Settings"])
@router.get("/settings", tags=["Settings"])
async def get_settings():
    return scheduler_service.settings.model_dump()

@router.post("/api/settings", tags=["Settings"])
@router.post("/settings", tags=["Settings"])
async def update_settings(req: SettingsUpdateRequest):
    if req.download_dir:
        scheduler_service.settings.download_dir = req.download_dir
        storage_service.set_directory(req.download_dir)
    if req.max_concurrent_downloads:
        scheduler_service.update_concurrency(req.max_concurrent_downloads)
    if req.auto_clear_completed is not None:
        scheduler_service.settings.auto_clear_completed = req.auto_clear_completed
    if req.default_quality:
        scheduler_service.settings.default_quality = req.default_quality
    return scheduler_service.settings.model_dump()

# -----------------------------------------------------------
# LINK INSPECTION
# -----------------------------------------------------------
@router.post("/api/analyze", tags=["Inspection"])
@router.post("/analyze", tags=["Inspection"])
async def analyze_links(req: AnalyzeBatchRequest):
    urls = [u.strip() for u in req.urls if u.strip()]
    if not urls:
        raise HTTPException(status_code=400, detail="No URLs provided")

    tasks = [inspection_service.analyze(u) for u in urls]
    results = await asyncio.gather(*tasks)
    return {"results": [r.model_dump() for r in results]}

# -----------------------------------------------------------
# JOB QUEUE & DOWNLOADS
# -----------------------------------------------------------
@router.post("/api/download", tags=["Downloads"])
@router.post("/download", tags=["Downloads"])
async def enqueue_downloads(req: EnqueueDownloadsRequest):
    if not req.items:
        raise HTTPException(status_code=400, detail="No items provided to download")

    enqueued_jobs = []
    for item in req.items:
        job = await scheduler_service.enqueue(
            url=item.url,
            title=item.title,
            format_id=item.format_id,
            format_label=item.format_label,
            thumbnail=item.thumbnail,
            platform=item.platform,
            priority=item.priority
        )
        enqueued_jobs.append(job.model_dump())

    return {"enqueued": enqueued_jobs}

@router.get("/api/jobs", tags=["Downloads"])
@router.get("/jobs", tags=["Downloads"])
async def get_jobs():
    jobs = scheduler_service.get_all_jobs()
    return {"jobs": [j.model_dump() for j in jobs]}

@router.post("/api/jobs/{job_id}/pause", tags=["Downloads"])
async def pause_job(job_id: str):
    success = await scheduler_service.pause_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or cannot be paused")
    return {"status": "paused", "job_id": job_id}

@router.post("/api/jobs/{job_id}/resume", tags=["Downloads"])
async def resume_job(job_id: str):
    job = await scheduler_service.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "resumed", "job": job.model_dump()}

@router.post("/api/jobs/{job_id}/cancel", tags=["Downloads"])
async def cancel_job(job_id: str):
    success = await scheduler_service.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or already completed")
    return {"status": "cancelled", "job_id": job_id}

@router.post("/api/jobs/{job_id}/retry", tags=["Downloads"])
async def retry_job(job_id: str):
    job = await scheduler_service.retry_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "retried", "job": job.model_dump()}

@router.delete("/api/jobs/{job_id}", tags=["Downloads"])
async def delete_job(job_id: str):
    success = scheduler_service.remove_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": "deleted", "job_id": job_id}

@router.post("/api/history/clear", tags=["Downloads"])
async def clear_history():
    count = scheduler_service.clear_history()
    return {"status": "cleared", "count": count}

@router.delete("/api/history", tags=["Downloads"])
async def delete_history():
    count = scheduler_service.clear_history()
    return {"status": "cleared", "count": count}

# -----------------------------------------------------------
# STORAGE INTEGRATION
# -----------------------------------------------------------
@router.post("/api/open-folder", tags=["Storage"])
async def open_download_folder():
    success = storage_service.open_folder()
    return {"success": success, "path": storage_service.base_dir}

@router.post("/api/open-file", tags=["Storage"])
async def open_downloaded_file(payload: Dict[str, Any]):
    path = payload.get("path")
    job_id = payload.get("job_id")
    if job_id and job_id in scheduler_service.jobs:
        path = scheduler_service.jobs[job_id].target_filepath

    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Target file does not exist on disk")
    if not path:
        raise HTTPException(status_code=400, detail="Target path is required")

    if not storage_service.is_safe_path(path):
        raise HTTPException(status_code=403, detail="Security violation: Target file is outside authorized download directory")

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Target file does not exist on disk")

    try:
        success = storage_service.open_file(path)
        return {"success": success, "path": path}
    except Exception as e:
        raise HTTPException(status_code=403, detail=str(e))

@router.get("/api/storage/disk-usage", tags=["Storage"])
async def get_disk_usage():
    return storage_service.get_disk_usage()

# -----------------------------------------------------------
# CLIPBOARD INTEGRATION
# -----------------------------------------------------------
@router.get("/api/clipboard", tags=["Clipboard"])
async def get_clipboard_content():
    """Retrieve current text and extracted URLs from native Windows clipboard."""
    from app.services.clipboard_service import clipboard_service
    text = clipboard_service.get_clipboard_text()
    urls = clipboard_service.extract_urls(text)
    return {
        "enabled": clipboard_service.enabled,
        "text": text,
        "urls": urls,
        "has_url": len(urls) > 0,
        "url": urls[0] if urls else None
    }

@router.post("/api/clipboard/toggle", tags=["Clipboard"])
async def toggle_clipboard_monitoring(payload: Dict[str, Any]):
    """Toggle real-time clipboard monitoring on/off."""
    from app.services.clipboard_service import clipboard_service
    enable = payload.get("enabled", True)
    clipboard_service.enabled = bool(enable)
    return {"enabled": clipboard_service.enabled}

# -----------------------------------------------------------
# WEBSOCKET STREAM
# -----------------------------------------------------------
@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_broadcaster.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_broadcaster.disconnect(ws)
    except Exception:
        ws_broadcaster.disconnect(ws)

