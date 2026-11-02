import os
import tempfile
import unittest
import httpx
from app.main import app
from app.domain.models import JobStatus, JobPriority
from app.domain.exceptions import PathTraversalSecurityException, InsufficientDiskSpaceException
from app.services.storage_service import StorageService
from app.services.scheduler_service import scheduler_service

class TestSecurityResilienceAndPersistence(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage = StorageService(self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_path_traversal_prevention(self):
        """Verify that paths outside the authorized storage directory are strictly blocked."""
        safe_file = os.path.join(self.temp_dir, "video.mp4")
        with open(safe_file, "w") as f:
            f.write("content")

        self.assertTrue(self.storage.is_safe_path(safe_file))

        # Malicious traversal paths
        unsafe_paths = [
            os.path.join(self.temp_dir, "..", "..", "Windows", "System32", "calc.exe"),
            "C:\\Windows\\System32\\cmd.exe",
            "/etc/passwd",
            os.path.join(self.temp_dir, "..", "secret.txt"),
            "../../relative/escape.txt"
        ]

        for unsafe_path in unsafe_paths:
            self.assertFalse(
                self.storage.is_safe_path(unsafe_path),
                f"Path traversal check failed for unsafe path: {unsafe_path}"
            )
            with self.assertRaises(PathTraversalSecurityException):
                self.storage.open_file(unsafe_path)

    async def test_api_open_file_security_rejection(self):
        """Verify that API endpoint /api/open-file rejects path traversal with HTTP 403."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/open-file", json={"path": "C:\\Windows\\System32\\notepad.exe"})
            res = await client.post("/api/open-file", json={"path": "../../secret.txt"})
            self.assertEqual(res.status_code, 403)
            self.assertIn("Security violation", res.json()["detail"])

    async def test_security_headers_and_cors(self):
        """Verify security headers (nosniff, SAMEORIGIN) and CORS origin policy."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/status", headers={"Origin": "https://drkanurag.github.io"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(res.headers.get("X-Frame-Options"), "SAMEORIGIN")
            self.assertEqual(res.headers.get("access-control-allow-origin"), "https://drkanurag.github.io")

    def test_disk_space_capacity_check(self):
        """Verify storage capacity check correctly detects insufficient disk space."""
        # Realistic small byte requirement should succeed
        self.assertTrue(self.storage.has_sufficient_space(1024))
        # Exorbitant petabyte requirement should safely return False
        self.assertFalse(self.storage.has_sufficient_space(10**18))

    async def test_pause_and_resume_job_flow(self):
        """Verify job transitions from QUEUED -> PAUSED -> QUEUED."""
        job = await scheduler_service.enqueue(
            url="https://example.com/test_pause_video.mp4",
            title="Pause Resume Test",
            format_id="direct"
        )
        job_id = job.id
        self.assertEqual(job.status, JobStatus.QUEUED)

        # Pause job
        paused = await scheduler_service.pause_job(job_id)
        self.assertTrue(paused)
        self.assertEqual(scheduler_service.jobs[job_id].status, JobStatus.PAUSED)
        self.assertIn(job_id, scheduler_service.paused_job_ids)

        # Resume job
        resumed_job = await scheduler_service.resume_job(job_id)
        self.assertIsNotNone(resumed_job)
        self.assertEqual(resumed_job.status, JobStatus.QUEUED)
        self.assertNotIn(job_id, scheduler_service.paused_job_ids)

        # Clean up
        scheduler_service.remove_job(job_id)

    async def test_api_pause_and_resume_endpoints(self):
        """Verify /api/jobs/{id}/pause and /api/jobs/{id}/resume API endpoints."""
        job = await scheduler_service.enqueue(
            url="https://example.com/test_api_pause.mp4",
            title="API Pause Test"
        )
        job_id = job.id

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res_pause = await client.post(f"/api/jobs/{job_id}/pause")
            self.assertEqual(res_pause.status_code, 200)
            self.assertEqual(res_pause.json()["status"], "paused")

            res_resume = await client.post(f"/api/jobs/{job_id}/resume")
            self.assertEqual(res_resume.status_code, 200)
            self.assertEqual(res_resume.json()["status"], "resumed")

        scheduler_service.remove_job(job_id)

    async def test_default_concurrency_ten(self):
        """Verify default concurrent downloads is configured to 10."""
        self.assertEqual(scheduler_service.settings.max_concurrent_downloads, 10)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/status")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["max_concurrent_downloads"], 10)

    async def test_auto_clear_completed_downloads(self):
        """Verify completed downloads are automatically cleared from memory and history."""
        self.assertTrue(scheduler_service.settings.auto_clear_completed)
        job = await scheduler_service.enqueue(
            url="https://example.com/test_autoclear.mp4",
            title="Auto Clear Test"
        )
        job_id = job.id
        self.assertIn(job_id, scheduler_service.jobs)

        # Mark completed and trigger purge
        job.status = JobStatus.COMPLETED
        await scheduler_service._delayed_purge_completed_job(job_id, delay_seconds=0.01)

        # Job must be completely purged from memory to save memory
        self.assertNotIn(job_id, scheduler_service.jobs)

    async def test_api_clear_history(self):
        """Verify /api/history/clear endpoint wipes history and reclaims memory."""
        job = await scheduler_service.enqueue(
            url="https://example.com/test_clear_hist.mp4",
            title="Clear History Test"
        )
        job.status = JobStatus.COMPLETED

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/history/clear")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "cleared")

        self.assertNotIn(job.id, scheduler_service.jobs)

    async def test_api_download_ssrf_rejection(self):
        """Verify /api/download rejects malicious SSRF URLs with 400 Bad Request."""
        malicious_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://localhost:8080/admin",
            "http://127.0.0.1:22/root",
            "http://10.0.0.1/secrets.json",
            "ftp://example.com/exploit"
        ]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for bad_url in malicious_urls:
                res = await client.post("/api/download", json={
                    "items": [{"url": bad_url, "title": "SSRF Test"}]
                })
                self.assertEqual(res.status_code, 400)
                self.assertIn("SSRF prevention", res.json()["detail"])

    async def test_api_analyze_batch_limit(self):
        """Verify /api/analyze rejects requests exceeding MAX_BATCH_URLS (25)."""
        urls = [f"https://example.com/video_{i}.mp4" for i in range(26)]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post("/api/analyze", json={"urls": urls})
            self.assertEqual(res.status_code, 400)
            self.assertIn("Maximum 25 URLs", res.json()["detail"])

    async def test_priority_queue_version_token_deduplication(self):
        """Verify that monotonic version tokens invalidate stale heap duplicates."""
        from app.dsa.priority_queue import PriorityQueue
        from app.domain.models import DownloadJob

        pq = PriorityQueue()
        job = DownloadJob(id="job_dedup_1", url="https://example.com/1.mp4", title="Dedup Test")
        
        # Initial push (version 1)
        await pq.push(job.id, job, priority=5)
        self.assertEqual(len(pq), 1)

        # Re-push with updated priority (increments version to 2, older heap entry invalidated)
        await pq.push(job.id, job, priority=1)
        self.assertEqual(len(pq), 1)

        # Pop should yield the item once with current version
        item_id, popped = await pq.pop()
        self.assertEqual(item_id, "job_dedup_1")
        self.assertEqual(popped.id, "job_dedup_1")
        self.assertEqual(len(pq), 0)

    async def test_pairing_token_authorization(self):
        """Verify external non-loopback origins require pairing token authentication."""
        from app.config import PAIRING_TOKEN
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # External origin without token -> 401 Unauthorized
            res_unauth = await client.post(
                "/api/settings",
                headers={"Origin": "https://zdownloader-rho.vercel.app"},
                json={"download_dir": "C:\\Downloads"}
            )
            self.assertEqual(res_unauth.status_code, 401)
            self.assertIn("Local engine pairing token required", res_unauth.json()["detail"])

            # External origin with valid token -> 200 OK
            res_auth = await client.post(
                "/api/settings",
                headers={
                    "Origin": "https://zdownloader-rho.vercel.app",
                    "X-API-Token": PAIRING_TOKEN
                },
                json={"download_dir": "C:\\Downloads"}
            )
            self.assertEqual(res_auth.status_code, 200)

    async def test_cloud_serverless_download_rejection(self):
        """Verify serverless cloud mode rejects /api/download and instructs local engine start."""
        os.environ["VERCEL"] = "1"
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                res = await client.post("/api/download", json={
                    "items": [{"url": "https://example.com/safe_video.mp4", "title": "Safe Video"}]
                })
                self.assertEqual(res.status_code, 400)
                self.assertIn("Media downloads require the Zdownloader Local Engine", res.json()["detail"])
        finally:
            os.environ.pop("VERCEL", None)

if __name__ == "__main__":
    unittest.main()

