import os
import uuid
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.routes import router
from app.services.scheduler_service import scheduler_service
from app.core.logger import correlation_id_ctx, logger

main_loop = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    # Microservice startup
    logger.info("Initializing Zdownloader Microservices...")
    await scheduler_service.start()
    from app.services.clipboard_service import clipboard_service
    clipboard_service.start()
    yield
    # Microservice graceful shutdown
    logger.info("Shutting down Zdownloader Microservices gracefully...")
    clipboard_service.stop()
    await scheduler_service.stop()

app = FastAPI(
    title="Zdownloader Microservices Engine",
    description="Universal Video Downloader built on Clean Architecture, Microservices & DSA",
    version="2.0.0",
    lifespan=lifespan
)

# Correlation / Trace ID Middleware
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())[:8]
    correlation_id_ctx.set(trace_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = trace_id
    return response

# Security Headers Middleware
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Restrict CORS to authorized origins only (Localhost, 127.0.0.1, and official GitHub Pages deployment)
ALLOWED_ORIGINS = [
    "https://drkanurag.github.io",
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "null"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://drkanurag\.github\.io$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(router)

# Mount static frontend
static_dir = Path(__file__).resolve().parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    if (static_dir / "css").exists():
        app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
    if (static_dir / "js").exists():
        app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")

    @app.get("/")
    async def serve_index():
        return FileResponse(str(static_dir / "index.html"))
