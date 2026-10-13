import os
import unittest
import asyncio
from app.utils import (
    get_ffmpeg_path,
    format_bytes,
    format_speed,
    format_seconds,
    sanitize_filename
)
from app.analyzer import is_direct_file_url, analyze_url
from app.models import DownloadJob, EnqueueItem
from app.config import AppSettings
from app.queue_manager import QueueManager

class TestZdownloader(unittest.IsolatedAsyncioTestCase):

    def test_ffmpeg_detection(self):
        ffmpeg_bin = get_ffmpeg_path()
        self.assertIsNotNone(ffmpeg_bin, "FFmpeg binary should be detected")
        self.assertTrue(os.path.exists(ffmpeg_bin), f"FFmpeg path should exist on disk: {ffmpeg_bin}")

    def test_format_helpers(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(1048576), "1.0 MB")
        self.assertEqual(format_bytes(1073741824), "1.0 GB")

        self.assertEqual(format_speed(0), "-- KB/s")
        self.assertEqual(format_speed(1048576), "1.0 MB/s")

        self.assertEqual(format_seconds(45), "00:45")
        self.assertEqual(format_seconds(125), "02:05")
        self.assertEqual(format_seconds(3665), "01:01:05")

    def test_sanitize_filename(self):
        dirty = 'My Video: Episode 1? [4K]/Special*Name<Here>|.mp4'
        clean = sanitize_filename(dirty)
        self.assertNotIn(":", clean)
        self.assertNotIn("?", clean)
        self.assertNotIn("/", clean)
        self.assertNotIn("*", clean)
        self.assertNotIn("<", clean)
        self.assertNotIn(">", clean)
        self.assertNotIn("|", clean)

    def test_direct_file_detection(self):
        self.assertTrue(is_direct_file_url("https://example.com/videos/sample.mp4"))
        self.assertTrue(is_direct_file_url("https://example.com/files/archive.zip"))
        self.assertFalse(is_direct_file_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    async def test_invalid_url_analysis(self):
        result = await analyze_url("ftp://invalid-url.com")
        self.assertEqual(result.status, "unsupported")
        self.assertIn("must start with http", result.error_message)

    async def test_queue_manager_enqueue(self):
        settings = AppSettings()
        qm = QueueManager(settings)
        items = [
            EnqueueItem(url="https://example.com/sample.mp4", title="Sample Test Video", format_id="direct")
        ]
        jobs = qm.enqueue_items(items)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.title, "Sample Test Video")
        self.assertEqual(job.format_id, "direct")
        self.assertIn(job.id, qm.jobs)
        # Cancel job so background task does not try to download dummy url
        await qm.cancel_job(job.id)

if __name__ == "__main__":
    unittest.main()

