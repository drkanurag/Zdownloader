import os
import json
import time
import uuid
import asyncio
from typing import Dict, List, Optional
from app.models import DownloadJob, EnqueueItem
from app.config import AppSettings, HISTORY_FILE
from app.downloader import download_direct_file, download_ytdlp, DownloadCancelledException
from app.websocket_manager import ws_manager
from app.analyzer import is_direct_file_url

class QueueManager:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.jobs: Dict[str, DownloadJob] = {}
        self.cancelled_job_ids: set[str] = set()
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self._load_history()

    def _load_history(self):
        """Load past completed jobs from disk if available."""
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        job = DownloadJob(**item)
                        self.jobs[job.id] = job
            except Exception as e:
                print(f"Error loading download history: {e}")

    def _save_history(self):
        """Save history of completed or failed downloads."""
        try:
            records = [job.model_dump() for job in self.jobs.values() if job.status in ("completed", "error")]
            # Keep the last 100 entries
            records = records[-100:]
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            print(f"Error saving download history: {e}")

    async def broadcast_job(self, job: DownloadJob):
        """Push real-time job update over WebSocket."""
        await ws_manager.broadcast({
            "type": "job_update",
            "job": job.model_dump()
        })

    def update_settings(self, max_concurrent: Optional[int] = None, download_dir: Optional[str] = None):
        if max_concurrent is not None and max_concurrent != self.settings.max_concurrent_downloads:
            self.settings.max_concurrent_downloads = max_concurrent
            self.semaphore = asyncio.Semaphore(max_concurrent)
        if download_dir:
            self.settings.download_dir = download_dir

    def enqueue_items(self, items: List[EnqueueItem]) -> List[DownloadJob]:
        """Create and queue new download jobs."""
        new_jobs: List[DownloadJob] = []
        for item in items:
            job_id = str(uuid.uuid4())
            job = DownloadJob(
                id=job_id,
                url=item.url,
                title=item.title or "Downloading Media",
                thumbnail=item.thumbnail,
                platform=item.platform or "Web",
                format_id=item.format_id or "best",
                format_label=item.format_label or "Original Quality",
                status="queued",
                download_dir=self.settings.download_dir,
                created_at=time.time()
            )
            self.jobs[job_id] = job
            new_jobs.append(job)

            # Spawn worker for this job
            task = asyncio.create_task(self._process_job(job))
            self.running_tasks[job_id] = task

        return new_jobs

    async def _process_job(self, job: DownloadJob):
        """Worker that acquires semaphore and executes the download."""
        async with self.semaphore:
            if job.id in self.cancelled_job_ids:
                job.status = "cancelled"
                await self.broadcast_job(job)
                return

            job.status = "downloading"
            await self.broadcast_job(job)

            async def on_progress(updated_job: DownloadJob):
                await self.broadcast_job(updated_job)

            def check_cancelled() -> bool:
                return job.id in self.cancelled_job_ids

            try:
                # Direct file or yt-dlp
                if job.format_id == "direct" or is_direct_file_url(job.url):
                    filepath = await download_direct_file(job, on_progress, check_cancelled)
                else:
                    filepath = await download_ytdlp(job, on_progress, check_cancelled)

                job.status = "completed"
                job.completed_at = time.time()
                job.target_filepath = filepath
                if filepath:
                    job.filename = os.path.basename(filepath)
                job.progress_percent = 100.0
                await self.broadcast_job(job)
                self._save_history()

            except DownloadCancelledException:
                job.status = "cancelled"
                job.error_message = "Cancelled by user"
                await self.broadcast_job(job)
            except Exception as e:
                job.status = "error"
                job.error_message = str(e)
                await self.broadcast_job(job)
                self._save_history()
            finally:
                if job.id in self.running_tasks:
                    del self.running_tasks[job.id]

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running or queued job."""
        if job_id not in self.jobs:
            return False
        job = self.jobs[job_id]
        if job.status in ("completed", "error", "cancelled"):
            return False

        self.cancelled_job_ids.add(job_id)
        job.status = "cancelled"
        job.error_message = "Cancelled by user"

        # If it was still queued and didn't start yet
        if job_id in self.running_tasks:
            task = self.running_tasks[job_id]
            task.cancel()

        await self.broadcast_job(job)
        return True

    def retry_job(self, job_id: str) -> Optional[DownloadJob]:
        """Retry a failed or cancelled job."""
        if job_id not in self.jobs:
            return None
        job = self.jobs[job_id]
        self.cancelled_job_ids.discard(job_id)
        job.status = "queued"
        job.progress_percent = 0.0
        job.downloaded_bytes = 0
        job.error_message = None
        job.speed_str = ""
        job.eta_str = ""

        task = asyncio.create_task(self._process_job(job))
        self.running_tasks[job_id] = task
        return job

    def remove_job(self, job_id: str) -> bool:
        """Remove a job from list."""
        if job_id in self.jobs:
            del self.jobs[job_id]
            self.cancelled_job_ids.discard(job_id)
            self._save_history()
            return True
        return False

    def get_all_jobs(self) -> List[DownloadJob]:
        """Get list of all jobs, most recent first."""
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

