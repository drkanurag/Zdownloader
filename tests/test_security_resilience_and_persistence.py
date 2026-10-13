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

if __name__ == "__main__":
    unittest.main()

