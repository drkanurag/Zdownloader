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
2. **Path Traversal Sandbox & Origin Security**:
   - Every file access is strictly bound to the authorized download directory using path normalization and canonical boundary checks (`is_safe_path`).
   - CORS is locked down to authorized local origins and the official GitHub Pages deployment domain, preventing drive-by attacks from arbitrary websites.
3. **HTTP Range & Transactional Streaming**:
   - Supports HTTP `Range: bytes=X-` headers and `206 Partial Content` for resumable downloads. Interrupted or paused downloads seamlessly resume from existing `.zpart` buffers.
4. **Persistent Queue State Across Restarts**:
   - Preserves pending, downloading, and paused jobs in `.zdownloader_queue.json`, restoring them seamlessly across app or daemon restarts.
5. **Circuit Breaker Pattern**:
   - Prevents downstream resource exhaustion when external media platforms experience transient outages or rate limits. Automatically shifts between `CLOSED`, `OPEN`, and `HALF_OPEN`.
6. **Structured Observability**:
   - Every incoming request and background task is tagged with an `X-Correlation-ID` header. Standardized JSON structured logs for distributed tracing.

---

## 🧩 2. Microservices Architecture (Bounded Contexts)

The system is decomposed into loosely-coupled, highly-cohesive domain services:

| Microservice | Bounded Context | Responsibilities |
|---|---|---|
| **Inspection Service** | `app.services.inspection_service` | Link validation, SSRF checks, LRU metadata caching, Trie-based domain categorization, yt-dlp probing |
| **Scheduler Service** | `app.services.scheduler_service` | Binary Min-Heap priority scheduling, persistent queue state, pause/resume flow, worker pool orchestration |
| **Download Service** | `app.services.download_service` | Chunked HTTP streaming with HTTP Range resume, bandwidth traffic shaping, sliding-window speed calculation, FFmpeg audio/video remuxing |
| **Storage Service** | `app.services.storage_service` | Local filesystem isolation, path traversal guards, disk capacity verification, safe filename sanitization, native Explorer integration |
| **Clipboard Service** | `app.services.clipboard_service` | Background monitoring of native Windows clipboard with automatic URL parsing and deduplication |
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
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
*(All 28 tests across DSA, System Design, Security, Persistence, and API suites pass with 100% success).*

---

## 🌐 4. Live Website & Deployment on GitHub

Zdownloader is accessible live on GitHub Pages:
👉 **[https://drkanurag.github.io/Zdownloader/](https://drkanurag.github.io/Zdownloader/)**

### ⚡ How to Use the Live Site with Your PC

1. Open **[https://drkanurag.github.io/Zdownloader/](https://drkanurag.github.io/Zdownloader/)** in any browser.
2. Run the local engine on your PC:
   ```powershell
   .\run_zdownloader.bat
   ```
3. The live website automatically detects your engine and turns **Agent Connected** (emerald green).
4. Videos download at maximum local line speed directly into your computer's `Downloads/Zdownloader` folder with lossless audio/video remuxing.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

