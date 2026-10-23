import unittest
import httpx
from app.main import app

class TestAPIEndpoints(unittest.IsolatedAsyncioTestCase):

    async def test_api_status(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/status")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "online")
            self.assertIn("version", data)
            self.assertTrue(data["ffmpeg_available"])
            # Verify Correlation-ID header middleware
            self.assertIn("X-Correlation-ID", res.headers)

    async def test_health_probes(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res_live = await client.get("/health/live")
            self.assertEqual(res_live.status_code, 200)
            self.assertEqual(res_live.json()["status"], "alive")

            res_ready = await client.get("/health/ready")
            self.assertEqual(res_ready.status_code, 200)
            self.assertEqual(res_ready.json()["status"], "ready")

    async def test_api_settings(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/settings")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertIn("download_dir", data)
            self.assertIn("max_concurrent_downloads", data)

    async def test_static_routes(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/")
            self.assertEqual(res.status_code, 200)
            self.assertIn("Zdownloader", res.text)

            res_css = await client.get("/static/css/style.css")
            self.assertEqual(res_css.status_code, 200)

            res_js = await client.get("/static/js/app.js")
            self.assertEqual(res_js.status_code, 200)

    async def test_vercel_entrypoint_and_serverless_mode(self):
        # Verify api.index entrypoint exports FastAPI app
        from api.index import app as vercel_app
        self.assertEqual(vercel_app.title, "Zdownloader Microservices Engine")

        # Test request handling in serverless mode
        transport = httpx.ASGITransport(app=vercel_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/status")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "online")
            self.assertEqual(data["mode"], "cloud_serverless")

if __name__ == "__main__":
    unittest.main()
