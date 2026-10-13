import os
import json
import time
import uuid
import asyncio
from typing import Dict, List, Optional
from app.domain.models import DownloadJob, JobStatus, JobPriority
from app.domain.events import JobCreatedEvent, JobProgressEvent, JobCompletedEvent, JobFailedEvent, JobCancelledEvent
from app.domain.exceptions import DownloadCancelledException, DownloadPausedException
from app.dsa.priority_queue import PriorityQueue
from app.core.event_bus import event_bus
from app.config import AppSettings, HISTORY_FILE, QUEUE_FILE
from app.services.download_service import download_service
from app.services.inspection_service import inspection_service

class SchedulerService:
    """
    Queue & Job Scheduling Microservice.
    
    Features:
      - Binary Min-Heap based Priority Queue for O(log N) scheduling
      - Worker pool with concurrency limits and semaphore control
      - Persistent queue state across application restarts (.zdownloader_queue.json)
      - Pause & Resumable job flow integration
      - EventBus pub/sub integration
      - Persistent download history
    """
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.jobs: Dict[str, DownloadJob] = {}
        self.queue: PriorityQueue[DownloadJob] = PriorityQueue()
        self.cancelled_job_ids: set[str] = set()
        self.paused_job_ids: set[str] = set()
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_downloads)
        self.workers: List[asyncio.Task] = []
        self._pending_startup_jobs: List[DownloadJob] = []
        self._is_running = False
        self._load_history()
        self._load_queue()

    def _load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        job = DownloadJob(**item)
                        # If auto_clear_completed is enabled, discard completed jobs to free memory
                        if self.settings.auto_clear_completed and job.status == JobStatus.COMPLETED:
                            continue
                        self.jobs[job.id] = job
            except Exception as e:
                print(f"Error loading download history: {e}")

    def _save_history(self):
        try:
            if self.settings.auto_clear_completed:
                # Do not write completed records to history file to minimize memory and disk usage
                records = [
                    job.model_dump() for job in self.jobs.values()
                    if job.status == JobStatus.FAILED
                ][-50:]
            else:
                records = [
                    job.model_dump() for job in self.jobs.values()
                    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
                ][-100:]
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            print(f"Error saving download history: {e}")

    def _load_queue(self):
        """Restore active and paused download tasks from previous session."""
        if os.path.exists(QUEUE_FILE):
            try:
                with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        job = DownloadJob(**item)
                        self.jobs[job.id] = job
                        if job.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING):
                            job.status = JobStatus.QUEUED
                            job.speed_str = ""
                            job.eta_str = ""
                            self._pending_startup_jobs.append(job)
                        elif job.status == JobStatus.PAUSED:
                            self.paused_job_ids.add(job.id)
            except Exception as e:
                print(f"Error loading download queue: {e}")

    def _save_queue(self):
        """Persist active, pending, and paused jobs to prevent data loss on restarts."""
        try:
            records = [
                job.model_dump() for job in self.jobs.values()
                if job.status in (JobStatus.QUEUED, JobStatus.DOWNLOADING, JobStatus.PAUSED)
            ]
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
        except Exception as e:
            print(f"Error saving download queue: {e}")

    async def start(self):
        """Start worker pool consumers and restore persisted pending jobs."""
        if self._is_running:
            return
        self._is_running = True

        # Re-enqueue jobs preserved from disk
        if self._pending_startup_jobs:
            for job in self._pending_startup_jobs:
                await self.queue.push(job.id, job, priority=job.priority)
            self._pending_startup_jobs.clear()

        # Spawn worker tasks matching concurrency capacity
        for _ in range(self.settings.max_concurrent_downloads):
            worker = asyncio.create_task(self._worker_loop())
            self.workers.append(worker)

    async def stop(self):
        """Gracefully stop worker pool and persist state."""
        self._is_running = False
        self._save_queue()
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
                    self._save_queue()
                    continue
                if job.id in self.paused_job_ids:
                    job.status = JobStatus.PAUSED
                    self._save_queue()
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
        self._save_queue()

        def check_cancelled() -> bool:
            return job.id in self.cancelled_job_ids

        def check_paused() -> bool:
            return job.id in self.paused_job_ids

        try:
            if job.format_id == "direct" or inspection_service.is_direct_file_url(job.url):
                filepath = await download_service.download_direct(job, check_cancelled, check_paused)
            else:
                filepath = await download_service.download_ytdlp(job, check_cancelled, check_paused)

            job.status = JobStatus.COMPLETED
            job.completed_at = time.time()
            job.target_filepath = filepath
            if filepath:
                job.filename = os.path.basename(filepath)
            job.progress_percent = 100.0

            await event_bus.publish(JobCompletedEvent(
                event_id=f"done-{job.id}",
                event_type="job_completed",
                job_id=job.id,
                filepath=filepath or "",
                filename=job.filename or "",
                total_bytes=job.downloaded_bytes
            ))

            if self.settings.auto_clear_completed:
                # Erase completed job from memory and disk history once finished on computer
                asyncio.create_task(self._delayed_purge_completed_job(job.id, delay_seconds=1.0))
            else:
                self._save_queue()
                self._save_history()

        except DownloadPausedException:
            job.status = JobStatus.PAUSED
            job.speed_str = "Paused"
            job.eta_str = ""
            self._save_queue()
            await event_bus.publish(JobProgressEvent(
                event_id=f"paused-{job.id}",
                event_type="job_progress",
                job_id=job.id,
                status=JobStatus.PAUSED.value,
                progress_percent=job.progress_percent,
                downloaded_bytes=job.downloaded_bytes,
                total_bytes=job.total_bytes,
                speed_str="Paused",
                eta_str=""
            ))

        except DownloadCancelledException:
            job.status = JobStatus.CANCELLED
            job.error_message = "Cancelled by user"
            self._save_queue()
            self._save_history()
            await event_bus.publish(JobCancelledEvent(
                event_id=f"canc-{job.id}",
                event_type="job_cancelled",
                job_id=job.id
            ))

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            self._save_queue()
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
        self.cancelled_job_ids.discard(job_id)
        self.paused_job_ids.discard(job_id)

        # Push into O(log N) Priority Queue
        await self.queue.push(job_id, job, priority=priority)
        self._save_queue()

        await event_bus.publish(JobCreatedEvent(
            event_id=f"created-{job_id}",
            event_type="job_created",
            job_id=job_id,
            url=url,
            title=job.title
        ))
        return job

    async def pause_job(self, job_id: str) -> bool:
        """Pause an active or queued job."""
        if job_id not in self.jobs:
            return False
        job = self.jobs[job_id]
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False

        self.paused_job_ids.add(job_id)
        job.status = JobStatus.PAUSED
        job.speed_str = "Paused"
        job.eta_str = ""
        await self.queue.remove(job_id)
        self._save_queue()

        await event_bus.publish(JobProgressEvent(
            event_id=f"pause-{job_id}",
            event_type="job_progress",
            job_id=job_id,
            status=JobStatus.PAUSED.value,
            progress_percent=job.progress_percent,
            downloaded_bytes=job.downloaded_bytes,
            total_bytes=job.total_bytes,
            speed_str="Paused",
            eta_str=""
        ))
        return True

    async def resume_job(self, job_id: str) -> Optional[DownloadJob]:
        """Resume a paused or interrupted job."""
        if job_id not in self.jobs:
            return None
        job = self.jobs[job_id]
        self.paused_job_ids.discard(job_id)
        self.cancelled_job_ids.discard(job_id)
        job.status = JobStatus.QUEUED
        job.speed_str = "Resuming..."
        job.error_message = None

        await self.queue.push(job_id, job, priority=job.priority)
        self._save_queue()

        await event_bus.publish(JobProgressEvent(
            event_id=f"resume-{job_id}",
            event_type="job_progress",
            job_id=job_id,
            status=JobStatus.QUEUED.value,
            progress_percent=job.progress_percent,
            downloaded_bytes=job.downloaded_bytes,
            total_bytes=job.total_bytes,
            speed_str="In Queue",
            eta_str=""
        ))
        return job

    async def cancel_job(self, job_id: str) -> bool:
        if job_id not in self.jobs:
            return False
        job = self.jobs[job_id]
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return False

        self.cancelled_job_ids.add(job_id)
        self.paused_job_ids.discard(job_id)
        job.status = JobStatus.CANCELLED
        job.error_message = "Cancelled by user"
        await self.queue.remove(job_id)
        self._save_queue()

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
        self.paused_job_ids.discard(job_id)
        job.status = JobStatus.QUEUED
        job.progress_percent = 0.0
        job.downloaded_bytes = 0
        job.error_message = None
        job.speed_str = ""
        job.eta_str = ""

        await self.queue.push(job_id, job, priority=job.priority)
        self._save_queue()
        return job

    def remove_job(self, job_id: str) -> bool:
        if job_id in self.jobs:
            del self.jobs[job_id]
            self.cancelled_job_ids.discard(job_id)
            self.paused_job_ids.discard(job_id)
            self._save_queue()
            self._save_history()
            return True
        return False

    async def _delayed_purge_completed_job(self, job_id: str, delay_seconds: float = 1.0):
        """Erase completed job from memory and persistence once safely written to disk."""
        try:
            await asyncio.sleep(delay_seconds)
            if job_id in self.jobs and self.jobs[job_id].status == JobStatus.COMPLETED:
                del self.jobs[job_id]
                self.cancelled_job_ids.discard(job_id)
                self.paused_job_ids.discard(job_id)
                self._save_queue()
                self._save_history()
        except Exception as e:
            print(f"Error purging completed job {job_id}: {e}")

    def clear_history(self) -> int:
        """Clear all finished or cancelled jobs to reclaim memory."""
        to_delete = [
            jid for jid, j in self.jobs.items()
            if j.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
        ]
        for jid in to_delete:
            del self.jobs[jid]
            self.cancelled_job_ids.discard(jid)
            self.paused_job_ids.discard(jid)

        self._save_history()
        self._save_queue()
        return len(to_delete)

    def update_concurrency(self, new_limit: int):
        """Dynamically adjust worker pool concurrency and semaphore."""
        if new_limit < 1:
            new_limit = 1
        self.settings.max_concurrent_downloads = new_limit
        self.semaphore = asyncio.Semaphore(new_limit)
        if self._is_running:
            diff = new_limit - len(self.workers)
            if diff > 0:
                for _ in range(diff):
                    worker = asyncio.create_task(self._worker_loop())
                    self.workers.append(worker)
            elif diff < 0:
                for _ in range(abs(diff)):
                    if self.workers:
                        w = self.workers.pop()
                        w.cancel()

    def get_all_jobs(self) -> List[DownloadJob]:
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

scheduler_service = SchedulerService(AppSettings())

