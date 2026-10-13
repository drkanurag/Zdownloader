# Zdownloader ⚡
> **Universal High-Speed Media & Video Downloader**  
> Architected following enterprise **System Design**, **Microservices**, and **Data Structures & Algorithms (DSA)** principles.

---

## 🏛️ 1. System Design Architecture

```
                    ┌────────────────────────────────────────────────────────┐
                    │            Client Web UI (Single Page App)             │
                    └──────────────────────────┬─────────────────────────────┘
                                               │ HTTP / WebSocket (Trace ID)
                                               ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                               API Gateway & Ingress Layer                                  │
│  - Correlation/Trace ID Middleware  - CORS Policy  - Rate Limiter (Token Bucket)           │
│  - Health Probes (/health/live, /health/ready)                                             │
└───────────────────┬──────────────────────────────────┬─────────────────────────────────────┘
                    │                                  │
                    ▼                                  ▼
┌───────────────────────────────────────┐  ┌─────────────────────────────────────────────────┐
│     Link Inspection Microservice      │  │        Job Scheduler Microservice               │
│ - SSRF / DNS Rebinding Protection     │  │ - Priority Queue (Binary Min-Heap, O(log N))    │
│ - LRU Cache with TTL (O(1))           │  │ - Concurrency Limiter (Async Semaphore)         │
│ - Domain Radix Trie (O(L))            │  │ - Persistent State & History                    │
│ - Circuit Breaker (CLOSED/OPEN/HALF)  │  │ - Worker Consumer Pool                          │
└───────────────────┬───────────────────┘  └───────────────────┬─────────────────────────────┘
                    │                                          │
                    │         ┌──────────────────────┐         │
                    └────────►│  Domain Event Bus    │◄────────┘
                              │  (Pub / Sub Pattern) │
                              └──────────┬───────────┘
                                         │
                                         ▼
┌────────────────────────────────────────────────────────────────────────────────────────────┐
│                             Download & Stream Processing Engine                            │
│  - Sliding Window Speed Estimator (Smoothing & Stable ETA)                                 │
│  - Token Bucket Bandwidth Throttle                                                         │
│  - Chunked Transactional Streaming (.zpart -> final)                                       │
│  - Bundled Standalone FFmpeg Remuxer (Lossless Video+Audio Muxing)                         │
└────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Key System Design Patterns
1. **SSRF & DNS Rebinding Defense**:
   - Every input URL is validated against RFC 1918 private IPv4/IPv6 networks, loopback addresses (`127.0.0.1`), link-local IPs, and cloud metadata endpoints (`169.254.169.254`).
2. **Circuit Breaker Pattern**:
   - Prevents downstream resource exhaustion when external media platforms experience transient outages or rate limits. Automatically shifts between `CLOSED`, `OPEN`, and `HALF_OPEN`.
3. **Structured Observability**:
   - Every incoming request and background task is tagged with an `X-Correlation-ID` header.
   - Standardized JSON structured logs for distributed tracing.
4. **Resilient Transactional Streaming**:
   - Files are written to `.zpart` temporary buffers during chunked ingestion and atomically swapped upon completion, preventing corrupted partial files.

---

## 🧩 2. Microservices Architecture (Bounded Contexts)

The system is decomposed into loosely-coupled, highly-cohesive domain services:

| Microservice | Bounded Context | Responsibilities |
|---|---|---|
| **Inspection Service** | `app.services.inspection_service` | Link validation, SSRF checks, LRU metadata caching, Trie-based domain categorization, yt-dlp probing |
| **Scheduler Service** | `app.services.scheduler_service` | Binary Min-Heap priority scheduling, worker pool orchestration, job state management |
| **Download Service** | `app.services.download_service` | Chunked HTTP streaming, bandwidth traffic shaping, sliding-window speed calculation, FFmpeg audio/video remuxing |
| **Storage Service** | `app.services.storage_service` | Local filesystem isolation, safe filename sanitization, disk usage reporting, native Explorer integration |
| **Event Bus** | `app.core.event_bus` | Asynchronous Pub/Sub domain event broker (`JobCreatedEvent`, `JobProgressEvent`, `JobCompletedEvent`, `JobFailedEvent`) |

---

## ⚡ 3. Data Structures & Algorithms (DSA)

| Algorithm / Data Structure | Implementation | Time Complexity | Purpose |
|---|---|---|---|
| **Binary Min-Heap** | `app.dsa.priority_queue.py` | Enqueue: $O(\log N)$<br>Dequeue: $O(\log N)$<br>Peek: $O(1)$ | Priority job scheduling with FIFO tie-breaking for equal priority tasks. |
| **LRU Cache with TTL** | `app.dsa.lru_cache.py` | Get: $O(1)$<br>Put: $O(1)$<br>Delete: $O(1)$ | Hash Map + Doubly Linked List caching analyzed URL formats with auto-expiration to prevent duplicate network calls. |
| **Sliding Window Moving Average** | `app.dsa.sliding_window.py` | Record: $O(1)$<br>Get Speed: $O(1)$ | Eliminates network packet jitter by calculating smooth, accurate download speed and ETA over a 2.0s time window. |
| **Token Bucket** | `app.dsa.token_bucket.py` | Acquire: $O(1)$ | Traffic shaping, rate limiting API calls, and enforcing bandwidth limits. |
| **Domain Radix Trie** | `app.dsa.trie.py` | Insert: $O(L)$<br>Search: $O(L)$ | Prefix tree matching reverse domain labels (`['com', 'youtube', 'm']`) for instant subdomain & wildcard classification. |

---

## 🚀 Running the System

### Option 1: 1-Click Launch on Windows
Double-click:
```bat
run_zdownloader.bat
```

### Option 2: Run via Terminal
```powershell
.\.venv\Scripts\python.exe start.py
```
Visit the web UI at: **`http://127.0.0.1:8765`**

### Running the Test Suite
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```
*(All 22 tests across DSA, System Design, Security, and API suites pass with 100% success).*

---

## 🌐 4. Live Website & Deployment on GitHub

Zdownloader is built as a **hybrid cloud-and-edge platform** (similar to JDownloader Web and WebTorrent). Anyone can access and use the live website directly from GitHub!

### 🌍 Accessing the Live Website
Once pushed to your GitHub repository, the live site is immediately available at:
```
https://<your-username>.github.io/<your-repository>/
```

### ⚡ 3 Ways to Use Zdownloader

#### Mode 1: Live GitHub Website + Local Engine (Recommended)
1. Open the live website: `https://<your-username>.github.io/<your-repository>/`
2. Run the local engine on your PC:
   ```powershell
   .\run_zdownloader.bat
   ```
   *(Or on Linux/Mac: `python start.py`)*
3. The live website automatically detects your engine and turns **Agent Connected** (emerald green).
4. Videos download at maximum local line speed directly into your computer's `Downloads/Zdownloader` folder with lossless audio/video remuxing.

#### Mode 2: 1-Click Free Cloud Backend (Docker / Render)
Deploy the full engine to the cloud for free so anyone can use it without running anything locally:
* **Deploy to Render:** Fork this repository, create a new Web Service on [Render.com](https://render.com), connect your repo, and Render will automatically detect [`render.yaml`](file:///c:/Users/anura/OneDrive%20-%20Manipal%20Academy%20of%20Higher%20Education/Desktop/Zdownloader/render.yaml) and [`Dockerfile`](file:///c:/Users/anura/OneDrive%20-%20Manipal%20Academy%20of%20Higher%20Education/Desktop/Zdownloader/Dockerfile).
* **Connect in Web UI:** Open the live website, click **Settings (⚙️)**, paste your Render URL (e.g., `https://zdownloader-engine.onrender.com`), and click **Save Settings**.

#### Mode 3: Standalone Local Web Interface
Run `.\run_zdownloader.bat` and visit `http://127.0.0.1:8765`.

---

## 📤 5. Publishing to GitHub (Step-by-Step)

To publish this project and activate your live GitHub website:

1. **Create a new empty repository on GitHub**:
   - Go to [github.com/new](https://github.com/new)
   - Repository name: `Zdownloader` (or any name you like)
   - Set to **Public**
   - Do **not** initialize with README or .gitignore (we already have them)

2. **Push the codebase from your terminal**:
   ```bash
   git add .
   git commit -m "feat: initial commit - universal video downloader with live GitHub Pages"
   git branch -M main
   git remote add origin https://github.com/<YOUR-USERNAME>/<YOUR-REPO-NAME>.git
   git push -u origin main
   ```

3. **Activate GitHub Pages**:
   - In your GitHub repo, go to **Settings** > **Pages**.
   - Under **Build and deployment** > **Source**:
     - Choose **GitHub Actions** (the automated [`deploy.yml`](file:///c:/Users/anura/OneDrive%20-%20Manipal%20Academy%20of%20Higher%20Education/Desktop/Zdownloader/.github/workflows/deploy.yml) workflow will test and publish your live website automatically!).
     - *Or* choose **Deploy from a branch** -> branch `main` -> folder `/docs`.
   - Your website is now live for the entire world at `https://<your-username>.github.io/<your-repo-name>/`!

