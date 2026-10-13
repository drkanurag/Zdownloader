import os
import json
import time
import uuid
import asyncio
from typing import Dict, List, Optional
from app.domain.models import DownloadJob, JobStatus, JobPriority
from app.domain.events import JobCreatedEvent, JobProgressEvent, JobCompletedEvent, JobFailedEvent, JobCancelledEvent
from app.domain.exceptions import DownloadCancelledException
from app.dsa.priority_queue import PriorityQueue
from app.core.event_bus import event_bus
from app.config import AppSettings, HISTORY_FILE
from app.services.download_service import download_service
from app.services.inspection_service import inspection_service

class SchedulerService:
    """
    Queue & Job Scheduling Microservice.
    
    Features:
      - Binary Min-Heap based Priority Queue for O(log N) scheduling
      - Worker pool with concurrency limits and semaphore control
      - EventBus pub/sub integration
      - Persistent history
    """
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.jobs: Dict[str, DownloadJob] = {}
        self.queue: PriorityQueue[DownloadJob] = PriorityQueue()
        self.cancelled_job_ids: set[str] = set()
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)
        self.workers: List[asyncio.Task] = []
        self._is_running = False
        self._load_history()

    def _load_history(self):
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
        try:
            records = [
                job.model_dump() for job in self.jobs.values()
                if job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
            ][-100:]
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            print(f"Error saving download history: {e}")

    async def start(self):
        """Start worker pool consumers."""
        if self._is_running:
            return
        self._is_running = True
        # Spawn worker tasks matching concurrency capacity
        for _ in range(self.settings.max_concurrent_downloads):
            worker = asyncio.create_task(self._worker_loop())
            self.workers.append(worker)

    async def stop(self):
        """Gracefully stop worker pool."""
        self._is_running = False
        for worker in self.workers:
            worker.cancel()
        self.workers.clear()

    async def _worker_loop(self):
        """Worker consuming jobs from Priority Queue."""
        while self._is_running:
            try:
                job_id, job = await self.queue.pop()
                if job.id in self.cancelled_job_ids:
                    job.status = JobStatus.CANCELLED
                    continue

                async with self.semaphore:
                    await self._execute_job(job)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Scheduler Worker Error]: {e}")
                await asyncio.sleep(0.5)

    async def _execute_job(self, job: DownloadJob):
        job.status = JobStatus.DOWNLOADING
        def check_cancelled() -> bool:
            return job.id in self.cancelled_job_ids

        try:
            if job.format_id == "direct" or inspection_service.is_direct_file_url(job.url):
                filepath = await download_service.download_direct(job, check_cancelled)
            else:
                filepath = await download_service.download_ytdlp(job, check_cancelled)

            job.status = JobStatus.COMPLETED
            job.completed_at = time.time()
            job.target_filepath = filepath
            if filepath:
                job.filename = os.path.basename(filepath)
            job.progress_percent = 100.0
            self._save_history()

        except DownloadCancelledException:
            job.status = JobStatus.CANCELLED
            job.error_message = "Cancelled by user"
            await event_bus.publish(JobCancelledEvent(
                event_id=f"canc-{job.id}",
                event_type="job_cancelled",
                job_id=job.id
            ))
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            self._save_history()
            await event_bus.publish(JobFailedEvent(
                event_id=f"fail-{job.id}",
                event_type="job_failed",
                job_id=job.id,
                error_message=str(e)
            ))

    async def enqueue(
        self,
        url: str,
        title: Optional[str] = None,
        format_id: str = "best",
        format_label: Optional[str] = None,
        thumbnail: Optional[str] = None,
        platform: Optional[str] = None,
        priority: int = JobPriority.NORMAL
    ) -> DownloadJob:
        job_id = str(uuid.uuid4())
        job = DownloadJob(
            id=job_id,
            url=url,
            title=title or "Downloading Media",
            thumbnail=thumbnail,
            platform=platform or "Web",
            format_id=format_id or "best",
            format_label=format_label or "Original Quality",
            priority=priority,
            status=JobStatus.QUEUED,
            download_dir=self.settings.download_dir,
            created_at=time.time()
        )
        self.jobs[job_id] = job
        # Push into O(log N) Priority Queue
        await self.queue.push(job_id, job, priority=priority)

        await event_bus.publish(JobCreatedEvent(
            event_id=f"created-{job_id}",
            event_type="job_created",
            job_id=job_id,
            url=url,
            title=job.title
        ))
        return job

    async def cancel_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        job = self.jobs[job_id]
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False

        self.cancelled_job_ids.add(job_id)
        job.status = JobStatus.CANCELLED
        job.error_message = "Cancelled by user"
        await self.queue.remove(job_id)

        await event_bus.publish(JobCancelledEvent(
            event_id=f"canc-{job_id}",
            event_type="job_cancelled",
            job_id=job_id
        ))
        return True

    async def retry_job(self, job_id: str) -> Optional[DownloadJob]:
        if job_id not in self.jobs:
            return None
        job = self.jobs[job_id]
        self.cancelled_job_ids.discard(job_id)
        job.status = JobStatus.QUEUED
        job.progress_percent = 0.0
        job.downloaded_bytes = 0
        job.error_message = None
        job.speed_str = ""
        job.eta_str = ""

        await self.queue.push(job_id, job, priority=job.priority)
        return job

    def remove_job(self, job_id: str) -> bool:
        if job_id in self.jobs:
            del self.jobs[job_id]
            self.cancelled_job_ids.discard(job_id)
            self._save_history()
            return True
        return False

    def get_all_jobs(self) -> List[DownloadJob]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

scheduler_service = SchedulerService(AppSettings())

