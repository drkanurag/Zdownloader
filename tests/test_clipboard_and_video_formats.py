import unittest
from app.services.clipboard_service import clipboard_service
from app.domain.models import DownloadJob

class TestClipboardAndVideoFormats(unittest.TestCase):

    def test_clipboard_url_extraction(self):
        text1 = "Hey check out this video https://www.youtube.com/watch?v=dQw4w9WgXcQ it is cool"
        urls1 = clipboard_service.extract_urls(text1)
        self.assertEqual(len(urls1), 1)
        self.assertEqual(urls1[0], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        text2 = "Multiple links:\nhttps://vimeo.com/123456\nhttps://example.com/file.mp4"
        urls2 = clipboard_service.extract_urls(text2)
        self.assertEqual(len(urls2), 2)
        self.assertEqual(urls2[0], "https://vimeo.com/123456")
        self.assertEqual(urls2[1], "https://example.com/file.mp4")

        # Non-URL text
        text3 = "Just some normal text with no link at all"
        urls3 = clipboard_service.extract_urls(text3)
        self.assertEqual(len(urls3), 0)

        # Concatenated URLs without whitespace
        text4 = "https://www.youtube.com/shorts/L48g2cAhrCI?feature=sharehttps://www.youtube.com/shorts/2DgRxMLMBJE?feature=share"
        urls4 = clipboard_service.extract_urls(text4)
        self.assertEqual(len(urls4), 2)
        self.assertEqual(urls4[0], "https://www.youtube.com/shorts/L48g2cAhrCI?feature=share")
        self.assertEqual(urls4[1], "https://www.youtube.com/shorts/2DgRxMLMBJE?feature=share")

    def test_video_format_selection_logic(self):
        # Default bestvideo+bestaudio should NOT be treated as audio-only
        format_id = "bestvideo+bestaudio/best"
        is_audio_only = (
            format_id == "bestaudio/best"
            or format_id == "audio_only"
            or (format_id.startswith("bestaudio") and "bestvideo" not in format_id and "+bestaudio" not in format_id)
        )
        self.assertFalse(is_audio_only, "bestvideo+bestaudio/best must not be audio only")

        # Explicit audio only
        fmt_audio = "bestaudio/best"
        is_audio_only_true = (
            fmt_audio == "bestaudio/best"
            or fmt_audio == "audio_only"
            or (fmt_audio.startswith("bestaudio") and "bestvideo" not in fmt_audio and "+bestaudio" not in fmt_audio)
        )
        self.assertTrue(is_audio_only_true, "bestaudio/best must be audio only")

    def test_download_job_float_bytes_validator(self):
        # Ensure float bytes from yt-dlp estimates are cleanly converted to integers
        job = DownloadJob(
            id="test-job-1",
            url="https://www.youtube.com/watch?v=123",
            title="Test",
            total_bytes=4969013.333333333,
            downloaded_bytes=1000.5
        )
        self.assertEqual(job.total_bytes, 4969013)
        self.assertEqual(job.downloaded_bytes, 1000)

if __name__ == "__main__":
    unittest.main()

