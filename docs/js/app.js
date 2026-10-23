/**
 * Zdownloader Frontend Client Application
 * Features:
 *  - Real-Time WebSockets & Auto-Reconnection
 *  - Native Windows Clipboard Auto-Detection (Direct Link Reader)
 *  - Robust Event Delegation for all action buttons
 *  - Format Inspection & Lossless Original Quality Downloads
 *  - Explorer File & Folder Launching
 */

function getInitialApiBase() {
  const saved = localStorage.getItem('zdownloader_api_base');
  if (saved && saved.trim()) return saved.trim().replace(/\/+$/, '');

  if (window.location.origin.includes('8765') || window.location.origin.includes('localhost') || window.location.origin.includes('127.0.0.1')) {
    return window.location.origin;
  }

  // By default, connect to the Local Engine at http://127.0.0.1:8765
  // so downloads save to the user's PC and YouTube is never blocked by datacenter rate-limits.
  return 'http://127.0.0.1:8765';
}

let API_BASE = getInitialApiBase();
let WS_BASE = API_BASE.replace(/^http/, 'ws') + '/ws';

function updateApiBase(newUrl) {
  if (!newUrl || !newUrl.trim()) {
    localStorage.removeItem('zdownloader_api_base');
    API_BASE = getInitialApiBase();
  } else {
    API_BASE = newUrl.trim().replace(/\/+$/, '');
    localStorage.setItem('zdownloader_api_base', API_BASE);
  }
  WS_BASE = API_BASE.replace(/^http/, 'ws') + '/ws';
  if (socket) {
    try { socket.close(); } catch (e) {}
  }
  connectWebSocket();
  fetchStatus();
  fetchJobs();
}

// State
let jobs = new Map();
let detectedItems = [];
let currentTab = 'active';
let isCloudMode = false;
let appSettings = null;
let socket = null;
let reconnectTimer = null;
let clipboardMonitorEnabled = true;
let autoClearCompleted = true;

// DOM Elements
const urlInput = document.getElementById('urlInput');
const analyzeBtn = document.getElementById('analyzeBtn');
const downloadAllBtn = document.getElementById('downloadAllBtn');
const pasteClipboardBtn = document.getElementById('pasteClipboardBtn');
const clearInputBtn = document.getElementById('clearInputBtn');

const inspectorSection = document.getElementById('inspectorSection');
const inspectorCardsList = document.getElementById('inspectorCardsList');
const detectedCount = document.getElementById('detectedCount');
const startAllSelectedBtn = document.getElementById('startAllSelectedBtn');
const dismissInspectorBtn = document.getElementById('dismissInspectorBtn');

const tabActiveBtn = document.getElementById('tabActiveBtn');
const tabHistoryBtn = document.getElementById('tabHistoryBtn');
const activeQueueContainer = document.getElementById('activeQueueContainer');
const historyContainer = document.getElementById('historyContainer');
const jobsList = document.getElementById('jobsList');
const historyList = document.getElementById('historyList');
const emptyQueueNotice = document.getElementById('emptyQueueNotice');
const emptyHistoryNotice = document.getElementById('emptyHistoryNotice');
const activeCountBadge = document.getElementById('activeCountBadge');
const historyCountBadge = document.getElementById('historyCountBadge');
const clearCompletedBtn = document.getElementById('clearCompletedBtn');
const clearHistoryBtn = document.getElementById('clearHistoryBtn');

let agentOnline = false;

const cloudMirrorBanner = document.getElementById('cloudMirrorBanner');
const bannerHelpBtn = document.getElementById('bannerHelpBtn');
const agentStatusBadge = document.getElementById('agentStatusBadge');
const agentStatusDot = document.getElementById('agentStatusDot');
const agentStatusPing = document.getElementById('agentStatusPing');
const agentStatusText = document.getElementById('agentStatusText');
const ffmpegBadge = document.getElementById('ffmpegBadge');
const ffmpegText = document.getElementById('ffmpegText');

const clipboardToggleBtn = document.getElementById('clipboardToggleBtn');
const clipboardToggleText = document.getElementById('clipboardToggleText');
const clipboardPing = document.getElementById('clipboardPing');
const clipboardDot = document.getElementById('clipboardDot');
const toastContainer = document.getElementById('toastContainer');

const openFolderBtn = document.getElementById('openFolderBtn');
const openFolderFooterBtn = document.getElementById('openFolderFooterBtn');
const openSettingsBtn = document.getElementById('openSettingsBtn');
const settingsModal = document.getElementById('settingsModal');
const closeSettingsBtn = document.getElementById('closeSettingsBtn');
const cancelSettingsBtn = document.getElementById('cancelSettingsBtn');
const saveSettingsBtn = document.getElementById('saveSettingsBtn');
const disconnectedModal = document.getElementById('disconnectedModal');
const retryConnectionBtn = document.getElementById('retryConnectionBtn');

const settingDownloadDir = document.getElementById('settingDownloadDir');
const settingDefaultQuality = document.getElementById('settingDefaultQuality');
const settingMaxConcurrent = document.getElementById('settingMaxConcurrent');
const settingMaxConcurrentVal = document.getElementById('settingMaxConcurrentVal');
const settingAutoClear = document.getElementById('settingAutoClear');
const settingFfmpegPath = document.getElementById('settingFfmpegPath');
const settingOpenFolderBtn = document.getElementById('settingOpenFolderBtn');

const settingApiBase = document.getElementById('settingApiBase');
const resetApiBaseBtn = document.getElementById('resetApiBaseBtn');
const activeApiBaseLabel = document.getElementById('activeApiBaseLabel');
const disconnectedApiBaseInput = document.getElementById('disconnectedApiBaseInput');
const saveDisconnectedApiBaseBtn = document.getElementById('saveDisconnectedApiBaseBtn');
const dismissDisconnectedBtn = document.getElementById('dismissDisconnectedBtn');

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return 'Unknown size';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val.toFixed(1)} ${units[i]}`;
}

// -------------------------------------------------------------
// TOAST NOTIFICATION ENGINE
// -------------------------------------------------------------
function showToast(title, message, actions = []) {
  if (!toastContainer) return;

  const toast = document.createElement('div');
  toast.className = 'pointer-events-auto bg-gray-900 border border-indigo-500/40 rounded-xl p-4 shadow-2xl max-w-sm w-full space-y-2 transition-all transform duration-300 translate-y-2 opacity-0';

  let actionsHtml = '';
  if (actions.length > 0) {
    actionsHtml = `
      <div class="flex items-center space-x-2 pt-1">
        ${actions.map((act, idx) => `
          <button class="toast-action-btn text-xs font-semibold px-3 py-1.5 rounded-lg ${act.primary ? 'bg-indigo-600 hover:bg-indigo-500 text-white' : 'bg-gray-800 hover:bg-gray-700 text-gray-300'} transition" data-idx="${idx}">
            ${act.label}
          </button>
        `).join('')}
      </div>
    `;
  }

  toast.innerHTML = `
    <div class="flex items-start justify-between gap-2">
      <div class="flex items-center space-x-2">
        <div class="w-7 h-7 rounded-lg bg-indigo-500/20 text-indigo-400 flex items-center justify-center flex-shrink-0">
          <i data-lucide="clipboard-check" class="w-4 h-4"></i>
        </div>
        <div>
          <h5 class="text-xs font-bold text-white">${title}</h5>
          <p class="text-[11px] text-gray-400 font-mono truncate max-w-[220px]">${message}</p>
        </div>
      </div>
      <button class="toast-close-btn text-gray-500 hover:text-gray-300 transition p-1">
        <i data-lucide="x" class="w-3.5 h-3.5"></i>
      </button>
    </div>
    ${actionsHtml}
  `;

  toastContainer.appendChild(toast);
  lucide.createIcons();

  requestAnimationFrame(() => {
    toast.classList.remove('translate-y-2', 'opacity-0');
  });

  const closeToast = () => {
    toast.classList.add('opacity-0', 'translate-y-2');
    setTimeout(() => toast.remove(), 300);
  };

  toast.querySelector('.toast-close-btn').addEventListener('click', closeToast);

  toast.querySelectorAll('.toast-action-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.idx, 10);
      if (actions[idx] && actions[idx].onClick) {
        actions[idx].onClick();
      }
      closeToast();
    });
  });

  // Auto-dismiss after 8 seconds
  setTimeout(closeToast, 8000);
}

// -------------------------------------------------------------
// WEBSOCKET & AGENT CONNECTION
// -------------------------------------------------------------
function connectWebSocket() {
  if (API_BASE.includes('vercel.app') || window.location.hostname.includes('vercel.app')) {
    // Vercel serverless functions do not sustain persistent WebSocket connections.
    // Use regular HTTP polling instead.
    return;
  }
  if (socket && socket.readyState === WebSocket.OPEN) return;

  try {
    socket = new WebSocket(WS_BASE);
  } catch (err) {
    setAgentStatus(false);
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    setAgentStatus(true);
    fetchStatus();
    fetchJobs();
    fetchClipboardStatus();
  };

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === 'job_update' && data.job) {
        handleJobUpdate(data.job);
      } else if (data.type === 'clipboard_detected' && data.url) {
        handleClipboardDetected(data.url, data.urls || []);
      }
    } catch (e) {
      console.error('Error handling WebSocket message:', e);
    }
  };

  socket.onclose = () => {
    setAgentStatus(false);
    scheduleReconnect();
  };

  socket.onerror = () => {
    setAgentStatus(false);
    socket.close();
  };
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connectWebSocket, 3000);
}

function setAgentStatus(online) {
  agentOnline = online;
  if (online) {
    agentStatusDot.className = 'relative inline-flex rounded-full h-2 w-2 bg-emerald-500';
    agentStatusPing.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75';
    agentStatusText.textContent = isCloudMode ? 'Cloud API Online' : 'Agent Connected';
    if (cloudMirrorBanner && !isCloudMode) cloudMirrorBanner.classList.add('hidden');
    disconnectedModal.classList.add('hidden');
  } else {
    agentStatusDot.className = 'relative inline-flex rounded-full h-2 w-2 bg-red-500';
    agentStatusPing.className = 'hidden';
    agentStatusText.textContent = 'Agent Disconnected';
    if (cloudMirrorBanner && (window.location.hostname.endsWith('github.io') || window.location.hostname.includes('vercel.app'))) {
      cloudMirrorBanner.classList.remove('hidden');
    }
  }
}

function showDisconnectedHelpModal() {
  disconnectedModal.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
}

// Ping heartbeat
setInterval(() => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send('ping');
  }
}, 25000);

// Periodic status & job sync fallback (when WebSocket is not connected or in cloud serverless mode)
setInterval(() => {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    fetchStatus();
    fetchJobs();
  }
}, 4000);

// -------------------------------------------------------------
// URL EXTRACTION & PARSING
// -------------------------------------------------------------
function extractUrlsFromText(text) {
  if (!text || typeof text !== 'string') return [];
  // Match all http/https links even if adjacent without spaces (e.g. sharehttps://...)
  const regex = /https?:\/\/(?:(?!https?:\/\/)[^\s<>"'`])+/gi;
  const matches = text.match(regex);
  if (matches && matches.length > 0) {
    const cleaned = matches.map(u => u.trim().replace(/[.,;)>\]]+$/, '')).filter(u => u.length > 0);
    return Array.from(new Set(cleaned));
  }
  return text.split('\n').map(u => u.trim()).filter(u => u.length > 0);
}

function getUrlsFromInput() {
  const text = urlInput.value.trim();
  if (!text) return [];
  return extractUrlsFromText(text);
}

// -------------------------------------------------------------
// CLIPBOARD AUTO-DETECTION & LINKGRABBER HANDLER
// -------------------------------------------------------------
let lastProcessedClipboardUrl = null;
let lastClipboardBrowserText = '';

async function handleClipboardDetected(url, allUrls) {
  if (!clipboardMonitorEnabled) return;

  // Extract all clean individual URLs from input/clipboard
  const rawUrls = (allUrls && allUrls.length > 0) ? allUrls : [url];
  const candidateUrls = [];
  rawUrls.forEach(u => {
    if (typeof u === 'string') {
      const extracted = extractUrlsFromText(u);
      candidateUrls.push(...extracted);
    }
  });

  const validUrls = Array.from(new Set(candidateUrls.map(u => u.trim()))).filter(u => u.startsWith('http://') || u.startsWith('https://'));
  if (validUrls.length === 0) return;

  const primaryUrl = validUrls[0];
  if (primaryUrl === lastProcessedClipboardUrl && validUrls.length === 1) return;
  lastProcessedClipboardUrl = primaryUrl;

  // Insert any missing URLs into textarea cleanly separated by newlines
  const currentExtracted = extractUrlsFromText(urlInput.value);
  const updatedLines = [...currentExtracted];
  validUrls.forEach(u => {
    if (!updatedLines.includes(u)) {
      updatedLines.push(u);
    }
  });
  urlInput.value = updatedLines.join('\n');

  // Filter out URLs that are already inspected or currently queued/downloading
  const urlsToAnalyze = validUrls.filter(u => {
    const inDetected = detectedItems.some(i => i.url === u);
    const inJobs = Array.from(jobs.values()).some(j => j.url === u && (j.status === 'queued' || j.status === 'downloading' || j.status === 'merging'));
    return !inDetected && !inJobs;
  });

  if (urlsToAnalyze.length === 0) return;

  // Floating toast alert with instant actions
  const toastTitle = urlsToAnalyze.length === 1 
    ? 'Link Auto-Captured from Clipboard' 
    : `${urlsToAnalyze.length} Links Auto-Captured from Clipboard`;
  const toastSubtitle = urlsToAnalyze.length === 1 ? urlsToAnalyze[0] : `${urlsToAnalyze.length} media links found`;

  showToast(toastTitle, toastSubtitle, [
    {
      label: 'Auto-Download All (MP4)',
      primary: true,
      onClick: async () => {
        const batch = urlsToAnalyze.map(u => {
          const item = detectedItems.find(i => i.url === u);
          const selFmt = item ? (item.formats || []).find(f => f.format_id === item.selected_format_id) || item.formats[0] : null;
          return {
            url: u,
            title: item ? item.title : 'Media Download',
            thumbnail: item ? item.thumbnail : null,
            platform: item ? item.platform : 'Web',
            format_id: item ? item.selected_format_id || 'best' : 'best',
            format_label: selFmt ? selFmt.label : 'Highest Quality MP4'
          };
        });
        await enqueueDownloadBatch(batch);
        detectedItems = detectedItems.filter(i => !urlsToAnalyze.includes(i.url));
        renderInspectorCards();
        switchTab('active');
      }
    }
  ]);

  // JDownloader Behavior: Automatically analyze and place in Detected Media
  try {
    const res = await fetch(`${API_BASE}/api/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls: urlsToAnalyze })
    });
    if (res.ok) {
      const data = await res.json();
      const results = data.results || [];
      results.forEach(resItem => {
        if (!detectedItems.some(item => item.url === resItem.url)) {
          detectedItems.unshift(resItem);
        }
      });
      renderInspectorCards();
      inspectorSection.classList.remove('hidden');
    }
  } catch (err) {
    console.error('Auto link grab analysis error:', err);
  }
}

// Browser Window Focus & Tab Visibility Auto-Clipboard Reader
async function checkBrowserClipboard() {
  if (!clipboardMonitorEnabled) return;
  try {
    if (!navigator.clipboard || !navigator.clipboard.readText) return;
    const text = await navigator.clipboard.readText();
    if (!text || text === lastClipboardBrowserText) return;
    lastClipboardBrowserText = text;
    const extracted = extractUrlsFromText(text);
    if (extracted.length > 0) {
      handleClipboardDetected(extracted[0], extracted);
    }
  } catch (e) {
    // Silent fail if browser clipboard permission prompt is dismissed
  }
}

window.addEventListener('focus', checkBrowserClipboard);
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    checkBrowserClipboard();
  }
});

// Active polling fallback for Windows clipboard (polls every 1200ms)
setInterval(async () => {
  if (!clipboardMonitorEnabled) return;
  // 1. Check API_BASE clipboard endpoint
  try {
    const res = await fetch(`${API_BASE}/api/clipboard`);
    if (res.ok) {
      const data = await res.json();
      if (data.enabled && data.has_url && data.urls && data.urls.length > 0) {
        handleClipboardDetected(data.url, data.urls);
        return;
      }
    }
  } catch (e) {}

  // 2. If running on a cloud mirror (Vercel/GitHub Pages), also query local engine at 127.0.0.1:8765
  if (!API_BASE.includes('127.0.0.1') && !API_BASE.includes('localhost')) {
    try {
      const localRes = await fetch('http://127.0.0.1:8765/api/clipboard');
      if (localRes.ok) {
        const localData = await localRes.json();
        if (localData.enabled && localData.has_url && localData.urls && localData.urls.length > 0) {
          handleClipboardDetected(localData.url, localData.urls);
        }
      }
    } catch (e) {}
  }
}, 1200);

async function fetchClipboardStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/clipboard`);
    if (!res.ok) return;
    const data = await res.json();
    setClipboardUI(data.enabled);
  } catch (e) {
    console.error('Error fetching clipboard status:', e);
  }
}

async function toggleClipboardMonitor() {
  clipboardMonitorEnabled = !clipboardMonitorEnabled;
  setClipboardUI(clipboardMonitorEnabled);
  try {
    await fetch(`${API_BASE}/api/clipboard/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: clipboardMonitorEnabled })
    });
  } catch (e) {
    console.error('Error saving clipboard toggle:', e);
  }
}

function setClipboardUI(enabled) {
  clipboardMonitorEnabled = enabled;
  if (enabled) {
    clipboardToggleBtn.className = 'flex items-center space-x-1.5 px-3 py-1.5 rounded-full bg-emerald-950/60 border border-emerald-800/40 text-xs text-emerald-300 hover:bg-emerald-900/60 transition';
    clipboardDot.className = 'relative inline-flex rounded-full h-2 w-2 bg-emerald-500';
    clipboardPing.className = 'animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75';
    clipboardToggleText.textContent = 'Clipboard Monitor: ON';
  } else {
    clipboardToggleBtn.className = 'flex items-center space-x-1.5 px-3 py-1.5 rounded-full bg-gray-800/60 border border-gray-700 text-xs text-gray-400 hover:bg-gray-800 transition';
    clipboardDot.className = 'relative inline-flex rounded-full h-2 w-2 bg-gray-500';
    clipboardPing.className = 'hidden';
    clipboardToggleText.textContent = 'Clipboard Monitor: OFF';
  }
}

// -------------------------------------------------------------
// REST API CALLS
// -------------------------------------------------------------
async function fetchStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/status`);
    if (!res.ok) throw new Error('Failed to fetch status');
    const data = await res.json();
    isCloudMode = (data.mode === 'cloud_serverless');
    setAgentStatus(true);

    if (isCloudMode) {
      agentStatusText.textContent = 'Cloud API Online';
      ffmpegText.textContent = 'Cloud Engine';
      ffmpegBadge.classList.remove('hidden');
      settingFfmpegPath.textContent = data.ffmpeg_path || 'Cloud Serverless';
    } else if (data.ffmpeg_available) {
      ffmpegText.textContent = 'FFmpeg 7.1 Active';
      ffmpegBadge.classList.remove('hidden');
      settingFfmpegPath.textContent = data.ffmpeg_path || 'Active';
    } else {
      ffmpegText.textContent = 'FFmpeg Missing';
      ffmpegBadge.classList.remove('hidden');
      settingFfmpegPath.textContent = 'Not found';
    }

    if (data.download_dir) {
      settingDownloadDir.value = data.download_dir;
    }
  } catch (err) {
    // If local engine is offline and we are visiting a cloud domain, auto-fallback to cloud API
    if (API_BASE.includes('127.0.0.1') && !window.location.origin.includes('127.0.0.1') && !window.location.origin.includes('localhost') && !window.location.hostname.endsWith('github.io')) {
      try {
        const cloudRes = await fetch(`${window.location.origin}/api/status`);
        if (cloudRes.ok) {
          const cloudData = await cloudRes.json();
          API_BASE = window.location.origin;
          isCloudMode = true;
          setAgentStatus(true);
          agentStatusText.textContent = 'Cloud Mode (Local Offline)';
          return;
        }
      } catch (e) {}
    }
    setAgentStatus(false);
  }
}

async function fetchJobs() {
  try {
    const res = await fetch(`${API_BASE}/api/jobs`);
    if (!res.ok) return;
    const data = await res.json();
    if (data.jobs) {
      jobs.clear();
      data.jobs.forEach(job => {
        // Discard completed jobs from frontend cache if autoClearCompleted is true
        if (autoClearCompleted && job.status === 'completed') return;
        jobs.set(job.id, job);
      });
      renderJobs();
    }
  } catch (err) {
    console.error('Error fetching jobs:', err);
  }
}

async function fetchSettings() {
  if (settingApiBase) {
    settingApiBase.value = localStorage.getItem('zdownloader_api_base') || API_BASE;
  }
  if (activeApiBaseLabel) {
    activeApiBaseLabel.textContent = API_BASE;
  }
  try {
    const res = await fetch(`${API_BASE}/api/settings`);
    if (!res.ok) return;
    appSettings = await res.json();
    settingDownloadDir.value = appSettings.download_dir || '';
    settingDefaultQuality.value = appSettings.default_quality || 'highest';
    settingMaxConcurrent.value = appSettings.max_concurrent_downloads || 10;
    settingMaxConcurrentVal.textContent = appSettings.max_concurrent_downloads || 10;
    if (settingAutoClear) {
      settingAutoClear.checked = appSettings.auto_clear_completed !== false;
      autoClearCompleted = settingAutoClear.checked;
    }
  } catch (err) {
    console.error('Error fetching settings:', err);
  }
}

async function saveSettings() {
  if (settingApiBase) {
    const entered = settingApiBase.value.trim();
    if (entered !== API_BASE) {
      updateApiBase(entered);
    }
  }

  const payload = {
    download_dir: settingDownloadDir.value.trim(),
    default_quality: settingDefaultQuality.value,
    max_concurrent_downloads: parseInt(settingMaxConcurrent.value, 10),
    auto_clear_completed: settingAutoClear ? settingAutoClear.checked : true
  };
  autoClearCompleted = payload.auto_clear_completed;
  try {
    const res = await fetch(`${API_BASE}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.ok) {
      settingsModal.classList.add('hidden');
      fetchStatus();
      if (autoClearCompleted) {
        // Erase any completed jobs currently in memory
        for (const [id, j] of jobs.entries()) {
          if (j.status === 'completed') jobs.delete(id);
        }
        renderJobs();
      }
    }
  } catch (err) {
    // If backend is remote/offline, still close settings since local API_BASE was saved
    settingsModal.classList.add('hidden');
  }
}

async function triggerOpenFolder() {
  try {
    await fetch(`${API_BASE}/api/open-folder`, { method: 'POST' });
  } catch (err) {
    alert('Error opening folder: ' + err.message);
  }
}

async function triggerOpenFile(jobId, filePath) {
  try {
    const res = await fetch(`${API_BASE}/api/open-file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: jobId, path: filePath })
    });
    if (!res.ok) {
      // Fallback: open parent download directory
      await triggerOpenFolder();
    }
  } catch (err) {
    await triggerOpenFolder();
  }
}

// -------------------------------------------------------------
// LINK ANALYSIS & FORMAT INSPECTION
// -------------------------------------------------------------

async function analyzeLinks(autoDownload = false) {
  const urls = getUrlsFromInput();
  if (urls.length === 0) {
    alert('Please paste or copy at least one video or file URL.');
    urlInput.focus();
    return;
  }

  // If local engine is not connected, open troubleshooting modal with 1-click launcher
  if (!agentOnline) {
    showDisconnectedHelpModal();
    return;
  }

  const btn = autoDownload ? downloadAllBtn : analyzeBtn;
  const originalHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="inline-block animate-spin mr-2">&#9696;</span> ${autoDownload ? 'Processing...' : 'Analyzing...'}`;

  try {
    const res = await fetch(`${API_BASE}/api/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls })
    });

    if (!res.ok) {
      throw new Error((await res.json()).detail || 'Failed to analyze links');
    }

    const data = await res.json();
    detectedItems = data.results || [];

    if (autoDownload) {
      const toEnqueue = detectedItems
        .filter(item => item.status === 'supported' || item.status === 'direct_file')
        .map(item => ({
          url: item.url,
          title: item.title,
          thumbnail: item.thumbnail,
          platform: item.platform,
          format_id: item.selected_format_id || 'best',
          format_label: item.formats && item.formats[0] ? item.formats[0].label : 'Highest Quality'
        }));

      if (toEnqueue.length > 0) {
        await enqueueDownloadBatch(toEnqueue);
        urlInput.value = '';
        inspectorSection.classList.add('hidden');
        switchTab('active');
      } else {
        renderInspectorCards();
        inspectorSection.classList.remove('hidden');
      }
    } else {
      renderInspectorCards();
      inspectorSection.classList.remove('hidden');
      inspectorSection.scrollIntoView({ behavior: 'smooth' });
    }

  } catch (err) {
    if (err.message && (err.message.includes('fetch') || err.message.includes('NetworkError') || err.message.includes('Failed to fetch'))) {
      setAgentStatus(false);
      showDisconnectedHelpModal();
    } else {
      alert('Error analyzing links: ' + err.message);
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = originalHtml;
    lucide.createIcons();
  }
}

function renderInspectorCards() {
  detectedCount.textContent = detectedItems.length;
  inspectorCardsList.innerHTML = '';

  if (detectedItems.length === 0) {
    inspectorSection.classList.add('hidden');
    return;
  }

  detectedItems.forEach((item, index) => {
    const card = document.createElement('div');
    card.className = 'media-card bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 shadow-lg';

    let thumbHtml = '';
    if (item.thumbnail) {
      thumbHtml = `
        <div class="relative w-full md:w-36 h-24 rounded-lg overflow-hidden bg-gray-950 flex-shrink-0 border border-gray-800">
          <img src="${item.thumbnail}" alt="" class="w-full h-full object-cover">
          ${item.duration_str ? `<span class="absolute bottom-1 right-1 px-1.5 py-0.5 rounded bg-black/80 text-[10px] text-white font-mono font-medium">${item.duration_str}</span>` : ''}
        </div>
      `;
    } else {
      thumbHtml = `
        <div class="w-full md:w-36 h-24 rounded-lg bg-gray-950/80 border border-gray-800 flex flex-col items-center justify-center text-gray-500 flex-shrink-0">
          <i data-lucide="${item.status === 'direct_file' ? 'file' : 'film'}" class="w-8 h-8 text-indigo-400/60 mb-1"></i>
          <span class="text-[10px] uppercase font-semibold tracking-wider text-gray-400">${item.platform || 'Media'}</span>
        </div>
      `;
    }

    let controlsHtml = '';
    if (item.status === 'supported' || item.status === 'direct_file') {
      const formatOptionsHtml = (item.formats || []).map(f => {
        const sizeTag = f.filesize_str ? ` (${f.filesize_str})` : '';
        return `<option value="${f.format_id}" ${f.format_id === item.selected_format_id ? 'selected' : ''}>${f.label}${sizeTag}</option>`;
      }).join('');

      controlsHtml = `
        <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 w-full md:w-auto">
          <select class="format-selector bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-xs text-gray-200 focus:outline-none focus:ring-1 focus:ring-indigo-500" data-index="${index}">
            ${formatOptionsHtml}
          </select>
          <button class="download-single-btn px-4 py-2 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-xs font-semibold text-white flex items-center justify-center gap-1.5 transition" data-index="${index}">
            <i data-lucide="download" class="w-3.5 h-3.5"></i>
            <span>Download</span>
          </button>
        </div>
      `;
    } else {
      const isDrm = item.status === 'drm_protected';
      controlsHtml = `
        <div class="px-3 py-2 rounded-lg ${isDrm ? 'bg-red-500/10 border-red-500/30 text-red-300' : 'bg-amber-500/10 border-amber-500/30 text-amber-300'} border text-xs max-w-md">
          <div class="font-semibold flex items-center gap-1">
            <i data-lucide="${isDrm ? 'shield-alert' : 'alert-circle'}" class="w-3.5 h-3.5"></i>
            ${isDrm ? 'DRM Protected Media' : 'Unsupported Content'}
          </div>
          <p class="text-[11px] opacity-90 mt-0.5">${item.error_message || 'Cannot download this link.'}</p>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="flex flex-col sm:flex-row items-start sm:items-center gap-4 flex-1 min-w-0">
        ${thumbHtml}
        <div class="space-y-1 min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              ${item.platform || 'Web'}
            </span>
            ${item.uploader ? `<span class="text-xs text-gray-400 truncate">${item.uploader}</span>` : ''}
          </div>
          <h4 class="text-sm font-semibold text-white truncate max-w-xl" title="${item.title}">${item.title}</h4>
          <p class="text-xs text-gray-500 truncate font-mono">${item.url}</p>
        </div>
      </div>
      <div class="flex items-center gap-2 w-full md:w-auto justify-end">
        ${controlsHtml}
        <button class="remove-detected-btn p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition" data-index="${index}" title="Remove link">
          <i data-lucide="trash" class="w-4 h-4"></i>
        </button>
      </div>
    `;

    inspectorCardsList.appendChild(card);
  });

  lucide.createIcons();
}

async function enqueueDownloadBatch(items) {
  if (!agentOnline) {
    showDisconnectedHelpModal();
    return;
  }
  try {
    const res = await fetch(`${API_BASE}/api/download`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items })
    });
    if (!res.ok) throw new Error('Failed to enqueue downloads');
    const data = await res.json();
    if (data.enqueued) {
      data.enqueued.forEach(job => jobs.set(job.id, job));
      renderJobs();
    }
  } catch (err) {
    if (err.message && (err.message.includes('fetch') || err.message.includes('NetworkError') || err.message.includes('Failed to fetch'))) {
      setAgentStatus(false);
      showDisconnectedHelpModal();
    } else {
      alert('Error queueing downloads: ' + err.message);
    }
  }
}

// -------------------------------------------------------------
// JOBS & QUEUE MANAGEMENT
// -------------------------------------------------------------
function handleJobUpdate(updatedJob) {
  const existing = jobs.get(updatedJob.id);
  jobs.set(updatedJob.id, updatedJob);

  if (updatedJob.status === 'completed' && (!existing || existing.status !== 'completed')) {
    showToast(
      '✓ Download Complete',
      `${updatedJob.filename || updatedJob.title} saved to your computer`,
      [
        {
          label: 'Show File',
          onClick: () => triggerOpenFile(updatedJob.id, updatedJob.target_filepath)
        }
      ]
    );

    if (autoClearCompleted) {
      setTimeout(() => {
        const cardElem = document.getElementById(`job-card-${updatedJob.id}`);
        if (cardElem) {
          cardElem.style.transition = 'all 0.5s ease';
          cardElem.style.opacity = '0';
          cardElem.style.transform = 'translateY(-10px)';
          setTimeout(() => {
            jobs.delete(updatedJob.id);
            renderJobs();
          }, 500);
        } else {
          jobs.delete(updatedJob.id);
          renderJobs();
        }
      }, 1500);
    }
  }

  const cardElem = document.getElementById(`job-card-${updatedJob.id}`);
  if (cardElem) {
    updateJobCardDOM(cardElem, updatedJob);
  } else {
    renderJobs();
  }
}

function updateJobCardDOM(card, job) {
  const progressBar = card.querySelector('.job-progress-bar');
  if (progressBar) {
    progressBar.style.width = `${job.progress_percent || 0}%`;
  }

  const percentText = card.querySelector('.job-percent-text');
  if (percentText) {
    percentText.textContent = `${job.progress_percent || 0}%`;
  }

  const speedText = card.querySelector('.job-speed-text');
  if (speedText) {
    speedText.textContent = job.speed_str || '';
  }

  const etaText = card.querySelector('.job-eta-text');
  if (etaText) {
    etaText.textContent = job.eta_str ? `ETA: ${job.eta_str}` : '';
  }

  const statusBadge = card.querySelector('.job-status-badge');
  if (statusBadge) {
    let badgeClass = 'bg-gray-800 text-gray-300 border-gray-700';
    let statusLabel = job.status;

    if (job.status === 'downloading') {
      badgeClass = 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20';
      statusLabel = 'Downloading Video';
    } else if (job.status === 'paused') {
      badgeClass = 'bg-amber-500/10 text-amber-400 border-amber-500/20';
      statusLabel = 'Paused';
    } else if (job.status === 'merging') {
      badgeClass = 'bg-purple-500/10 text-purple-400 border-purple-500/20';
      statusLabel = 'Merging Streams';
    } else if (job.status === 'completed') {
      badgeClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
      statusLabel = 'Completed';
    } else if (job.status === 'error') {
      badgeClass = 'bg-red-500/10 text-red-400 border-red-500/20';
      statusLabel = 'Failed';
    } else if (job.status === 'cancelled') {
      badgeClass = 'bg-gray-800 text-gray-400 border-gray-700';
      statusLabel = 'Cancelled';
    }

    statusBadge.className = `job-status-badge px-2.5 py-0.5 rounded-full text-xs font-medium border ${badgeClass}`;
    statusBadge.textContent = statusLabel;
  }

  if (job.status === 'completed' || job.status === 'error' || job.status === 'cancelled' || job.status === 'paused') {
    renderJobs();
  }
}

function renderJobs() {
  const allJobs = Array.from(jobs.values()).sort((a, b) => b.created_at - a.created_at);
  const activeJobs = allJobs.filter(j => j.status === 'queued' || j.status === 'downloading' || j.status === 'merging' || j.status === 'paused');
  const historyJobs = allJobs.filter(j => j.status === 'completed' || j.status === 'error' || j.status === 'cancelled');

  activeCountBadge.textContent = activeJobs.length;
  historyCountBadge.textContent = historyJobs.length;

  if (activeJobs.length === 0) {
    emptyQueueNotice.classList.remove('hidden');
    jobsList.innerHTML = '';
  } else {
    emptyQueueNotice.classList.add('hidden');
    jobsList.innerHTML = activeJobs.map(j => createJobCardHtml(j, false)).join('');
  }

  if (historyJobs.length === 0) {
    emptyHistoryNotice.classList.remove('hidden');
    historyList.innerHTML = '';
  } else {
    emptyHistoryNotice.classList.add('hidden');
    historyList.innerHTML = historyJobs.map(j => createJobCardHtml(j, true)).join('');
  }

  lucide.createIcons();
}

function createJobCardHtml(job, isHistory) {
  let thumbHtml = '';
  if (job.thumbnail) {
    thumbHtml = `
      <div class="w-16 h-12 rounded-lg overflow-hidden bg-gray-950 flex-shrink-0 border border-gray-800">
        <img src="${job.thumbnail}" alt="" class="w-full h-full object-cover">
      </div>
    `;
  } else {
    thumbHtml = `
      <div class="w-16 h-12 rounded-lg bg-gray-950 border border-gray-800 flex items-center justify-center text-gray-500 flex-shrink-0">
        <i data-lucide="video" class="w-5 h-5 text-indigo-400/50"></i>
      </div>
    `;
  }

  let statusBadgeClass = 'bg-gray-800 text-gray-300 border-gray-700';
  let statusText = job.status;

  if (job.status === 'downloading') {
    statusBadgeClass = 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20';
    statusText = 'Downloading Video';
  } else if (job.status === 'paused') {
    statusBadgeClass = 'bg-amber-500/10 text-amber-400 border-amber-500/20';
    statusText = 'Paused';
  } else if (job.status === 'merging') {
    statusBadgeClass = 'bg-purple-500/10 text-purple-400 border-purple-500/20';
    statusText = 'Merging Audio & Video';
  } else if (job.status === 'completed') {
    statusBadgeClass = 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20';
    statusText = 'Completed';
  } else if (job.status === 'error') {
    statusBadgeClass = 'bg-red-500/10 text-red-400 border-red-500/20';
    statusText = 'Failed';
  } else if (job.status === 'cancelled') {
    statusBadgeClass = 'bg-gray-800 text-gray-400 border-gray-700';
    statusText = 'Cancelled';
  }

  let actionsHtml = '';
  if (job.status === 'downloading' || job.status === 'queued') {
    actionsHtml = `
      <button class="job-pause-btn p-2 rounded-lg text-gray-400 hover:text-amber-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Pause Download">
        <i data-lucide="pause" class="w-4 h-4"></i>
      </button>
      <button class="job-cancel-btn p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Cancel Download">
        <i data-lucide="x-circle" class="w-4 h-4"></i>
      </button>
    `;
  } else if (job.status === 'paused') {
    actionsHtml = `
      <button class="job-resume-btn p-2 rounded-lg text-gray-400 hover:text-emerald-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Resume Download">
        <i data-lucide="play" class="w-4 h-4"></i>
      </button>
      <button class="job-cancel-btn p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Cancel Download">
        <i data-lucide="x-circle" class="w-4 h-4"></i>
      </button>
    `;
  } else if (job.status === 'merging') {
    actionsHtml = `
      <button class="job-cancel-btn p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Cancel Download">
        <i data-lucide="x-circle" class="w-4 h-4"></i>
      </button>
    `;
  } else if (job.status === 'completed') {
    actionsHtml = `
      <button class="job-open-btn flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 text-xs font-medium text-gray-200 transition" data-id="${job.id}" data-path="${job.target_filepath || ''}" title="Open File in Explorer">
        <i data-lucide="folder-check" class="w-3.5 h-3.5 text-emerald-400"></i>
        <span>Show File</span>
      </button>
      <button class="job-remove-btn p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Delete Record">
        <i data-lucide="trash-2" class="w-4 h-4"></i>
      </button>
    `;
  } else {
    actionsHtml = `
      <button class="job-retry-btn p-2 rounded-lg text-gray-400 hover:text-indigo-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Retry Download">
        <i data-lucide="rotate-ccw" class="w-4 h-4"></i>
      </button>
      <button class="job-remove-btn p-2 rounded-lg text-gray-400 hover:text-red-400 hover:bg-gray-800 transition" data-id="${job.id}" title="Delete Record">
        <i data-lucide="trash-2" class="w-4 h-4"></i>
      </button>
    `;
  }

  const isIndeterminate = (job.status === 'merging' || (job.status === 'downloading' && job.progress_percent === 0));

  return `
    <div id="job-card-${job.id}" class="media-card bg-gray-900 border border-gray-800/80 rounded-xl p-4 space-y-3 shadow-md">
      <div class="flex items-center justify-between gap-4">
        <div class="flex items-center gap-3 min-w-0 flex-1">
          ${thumbHtml}
          <div class="min-w-0 flex-1 space-y-0.5">
            <div class="flex items-center gap-2">
              <span class="job-status-badge px-2.5 py-0.5 rounded-full text-[11px] font-medium border ${statusBadgeClass}">
                ${statusText}
              </span>
              <span class="text-xs text-indigo-400/90 font-mono">${job.format_label || 'Original Quality'}</span>
              <span class="text-[10px] text-gray-500 font-semibold uppercase px-1.5 py-0.2 rounded bg-gray-800">${job.platform || 'Web'}</span>
            </div>
            <h4 class="text-sm font-semibold text-white truncate max-w-xl" title="${job.title}">${job.title}</h4>
            ${job.filename ? `<p class="text-[11px] text-gray-400 font-mono truncate">${job.filename}</p>` : ''}
          </div>
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          ${actionsHtml}
        </div>
      </div>

      ${job.error_message ? `
        <div class="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/20 text-xs text-red-300">
          ${job.error_message}
        </div>
      ` : ''}

      ${!isHistory ? `
        <div class="space-y-1.5">
          <div class="h-2 w-full bg-gray-950 rounded-full overflow-hidden border border-gray-800 relative">
            <div
              class="job-progress-bar h-full bg-gradient-to-r from-indigo-500 via-indigo-600 to-purple-500 rounded-full transition-all duration-300 ${isIndeterminate ? 'progress-bar-animated w-full' : ''}"
              style="width: ${isIndeterminate ? '100%' : (job.progress_percent || 0) + '%'}"
            ></div>
          </div>
          <div class="flex items-center justify-between text-xs text-gray-400 font-mono">
            <div class="flex items-center space-x-3">
              <span class="job-percent-text text-gray-200 font-semibold">${job.progress_percent || 0}%</span>
              <span class="job-speed-text text-indigo-300">${job.speed_str || ''}</span>
              ${job.downloaded_bytes ? `<span>${formatBytes(job.downloaded_bytes)} ${job.total_bytes ? '/ ' + formatBytes(job.total_bytes) : ''}</span>` : ''}
            </div>
            <div>
              <span class="job-eta-text text-gray-500">${job.eta_str ? 'ETA: ' + job.eta_str : ''}</span>
            </div>
          </div>
        </div>
      ` : ''}
    </div>
  `;
}

function switchTab(tab) {
  currentTab = tab;
  if (tab === 'active') {
    tabActiveBtn.className = 'flex items-center space-x-2 px-4 py-2 rounded-lg bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 font-medium text-sm transition';
    tabHistoryBtn.className = 'flex items-center space-x-2 px-4 py-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800/60 font-medium text-sm transition';
    activeQueueContainer.classList.remove('hidden');
    historyContainer.classList.add('hidden');
  } else {
    tabHistoryBtn.className = 'flex items-center space-x-2 px-4 py-2 rounded-lg bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 font-medium text-sm transition';
    tabActiveBtn.className = 'flex items-center space-x-2 px-4 py-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-gray-800/60 font-medium text-sm transition';
    historyContainer.classList.remove('hidden');
    activeQueueContainer.classList.add('hidden');
  }
}

// -------------------------------------------------------------
// ROBUST EVENT DELEGATION FOR ALL BUTTONS
// -------------------------------------------------------------

// Active Queue Actions Delegation
jobsList.addEventListener('click', async (e) => {
  const pauseBtn = e.target.closest('.job-pause-btn');
  if (pauseBtn) {
    const jobId = pauseBtn.dataset.id;
    await fetch(`${API_BASE}/api/jobs/${jobId}/pause`, { method: 'POST' });
    return;
  }

  const resumeBtn = e.target.closest('.job-resume-btn');
  if (resumeBtn) {
    const jobId = resumeBtn.dataset.id;
    await fetch(`${API_BASE}/api/jobs/${jobId}/resume`, { method: 'POST' });
    return;
  }

  const cancelBtn = e.target.closest('.job-cancel-btn');
  if (cancelBtn) {
    const jobId = cancelBtn.dataset.id;
    await fetch(`${API_BASE}/api/jobs/${jobId}/cancel`, { method: 'POST' });
    return;
  }

  const openBtn = e.target.closest('.job-open-btn');
  if (openBtn) {
    const jobId = openBtn.dataset.id;
    const path = openBtn.dataset.path;
    await triggerOpenFile(jobId, path);
    return;
  }

  const removeBtn = e.target.closest('.job-remove-btn');
  if (removeBtn) {
    const jobId = removeBtn.dataset.id;
    await fetch(`${API_BASE}/api/jobs/${jobId}`, { method: 'DELETE' });
    jobs.delete(jobId);
    renderJobs();
    return;
  }
});

// History List Actions Delegation
historyList.addEventListener('click', async (e) => {
  const openBtn = e.target.closest('.job-open-btn');
  if (openBtn) {
    const jobId = openBtn.dataset.id;
    const path = openBtn.dataset.path;
    await triggerOpenFile(jobId, path);
    return;
  }

  const retryBtn = e.target.closest('.job-retry-btn');
  if (retryBtn) {
    const jobId = retryBtn.dataset.id;
    await fetch(`${API_BASE}/api/jobs/${jobId}/retry`, { method: 'POST' });
    switchTab('active');
    return;
  }

  const removeBtn = e.target.closest('.job-remove-btn');
  if (removeBtn) {
    const jobId = removeBtn.dataset.id;
    await fetch(`${API_BASE}/api/jobs/${jobId}`, { method: 'DELETE' });
    jobs.delete(jobId);
    renderJobs();
    return;
  }
});

// Inspector Cards Actions Delegation
inspectorCardsList.addEventListener('click', async (e) => {
  const downloadBtn = e.target.closest('.download-single-btn');
  if (downloadBtn) {
    const idx = parseInt(downloadBtn.dataset.index, 10);
    const item = detectedItems[idx];
    if (item) {
      const selFmt = (item.formats || []).find(f => f.format_id === item.selected_format_id) || item.formats[0];
      await enqueueDownloadBatch([{
        url: item.url,
        title: item.title,
        thumbnail: item.thumbnail,
        platform: item.platform,
        format_id: item.selected_format_id || 'best',
        format_label: selFmt ? selFmt.label : 'Highest Quality'
      }]);
      detectedItems.splice(idx, 1);
      renderInspectorCards();
      switchTab('active');
    }
    return;
  }

  const removeBtn = e.target.closest('.remove-detected-btn');
  if (removeBtn) {
    const idx = parseInt(removeBtn.dataset.index, 10);
    detectedItems.splice(idx, 1);
    renderInspectorCards();
    return;
  }
});

inspectorCardsList.addEventListener('change', (e) => {
  const formatSelect = e.target.closest('.format-selector');
  if (formatSelect) {
    const idx = parseInt(formatSelect.dataset.index, 10);
    if (detectedItems[idx]) {
      detectedItems[idx].selected_format_id = formatSelect.value;
    }
  }
});

// Primary Actions
analyzeBtn.addEventListener('click', () => analyzeLinks(false));
downloadAllBtn.addEventListener('click', () => analyzeLinks(true));

startAllSelectedBtn.addEventListener('click', async () => {
  const toEnqueue = detectedItems
    .filter(item => item.status === 'supported' || item.status === 'direct_file')
    .map(item => {
      const selFmt = (item.formats || []).find(f => f.format_id === item.selected_format_id) || item.formats[0];
      return {
        url: item.url,
        title: item.title,
        thumbnail: item.thumbnail,
        platform: item.platform,
        format_id: item.selected_format_id || 'best',
        format_label: selFmt ? selFmt.label : 'Highest Quality'
      };
    });

  if (toEnqueue.length > 0) {
    await enqueueDownloadBatch(toEnqueue);
    detectedItems = [];
    renderInspectorCards();
    switchTab('active');
  }
});

dismissInspectorBtn.addEventListener('click', () => {
  detectedItems = [];
  renderInspectorCards();
});

clearInputBtn.addEventListener('click', () => {
  urlInput.value = '';
  urlInput.focus();
});

// Paste Clipboard Button with fallback to Agent Win32 API
pasteClipboardBtn.addEventListener('click', async () => {
  // First attempt: fetch directly from local agent's native Windows clipboard reader!
  try {
    const res = await fetch(`${API_BASE}/api/clipboard`);
    if (res.ok) {
      const data = await res.json();
      if (data.text && data.text.trim()) {
        const text = data.text.trim();
        urlInput.value = urlInput.value.trim() ? `${urlInput.value.trim()}\n${text}` : text;
        showToast('Pasted from Windows Clipboard', text);
        return;
      }
    }
  } catch (e) {
    // Agent fetch failed, fallback to browser clipboard API
  }

  // Second attempt: browser navigator.clipboard
  try {
    const text = await navigator.clipboard.readText();
    if (text && text.trim()) {
      urlInput.value = urlInput.value.trim() ? `${urlInput.value.trim()}\n${text.trim()}` : text.trim();
    }
  } catch (e) {
    alert('Please use Ctrl+V to paste your link.');
  }
});

clipboardToggleBtn.addEventListener('click', toggleClipboardMonitor);

tabActiveBtn.addEventListener('click', () => switchTab('active'));
tabHistoryBtn.addEventListener('click', () => switchTab('history'));

if (clearCompletedBtn) {
  clearCompletedBtn.addEventListener('click', async () => {
    try {
      await fetch(`${API_BASE}/api/history/clear`, { method: 'POST' });
    } catch (e) {}
    const completedIds = Array.from(jobs.values())
      .filter(j => j.status === 'completed' || j.status === 'cancelled' || j.status === 'error')
      .map(j => j.id);

    for (const id of completedIds) {
      jobs.delete(id);
    }
    renderJobs();
  });
}

if (clearHistoryBtn) {
  clearHistoryBtn.addEventListener('click', async () => {
    try {
      await fetch(`${API_BASE}/api/history/clear`, { method: 'POST' });
    } catch (e) {}
    for (const [id, j] of jobs.entries()) {
      if (j.status === 'completed' || j.status === 'error' || j.status === 'cancelled') {
        jobs.delete(id);
      }
    }
    renderJobs();
    showToast('History Cleared', 'Download history and caches have been erased.');
  });
}

openFolderBtn.addEventListener('click', triggerOpenFolder);
openFolderFooterBtn.addEventListener('click', triggerOpenFolder);
settingOpenFolderBtn.addEventListener('click', triggerOpenFolder);

openSettingsBtn.addEventListener('click', () => {
  fetchSettings();
  settingsModal.classList.remove('hidden');
});
closeSettingsBtn.addEventListener('click', () => settingsModal.classList.add('hidden'));
cancelSettingsBtn.addEventListener('click', () => settingsModal.classList.add('hidden'));
saveSettingsBtn.addEventListener('click', saveSettings);

settingMaxConcurrent.addEventListener('input', (e) => {
  settingMaxConcurrentVal.textContent = e.target.value;
});

retryConnectionBtn.addEventListener('click', () => {
  connectWebSocket();
  fetchStatus();
});

if (agentStatusBadge) {
  agentStatusBadge.addEventListener('click', () => {
    if (!agentOnline) {
      showDisconnectedHelpModal();
    } else {
      fetchSettings();
      settingsModal.classList.remove('hidden');
    }
  });
}

if (bannerHelpBtn) {
  bannerHelpBtn.addEventListener('click', () => {
    showDisconnectedHelpModal();
  });
}

if (resetApiBaseBtn) {
  resetApiBaseBtn.addEventListener('click', () => {
    updateApiBase('');
    if (settingApiBase) settingApiBase.value = API_BASE;
    if (activeApiBaseLabel) activeApiBaseLabel.textContent = API_BASE;
  });
}

if (saveDisconnectedApiBaseBtn && disconnectedApiBaseInput) {
  saveDisconnectedApiBaseBtn.addEventListener('click', () => {
    const val = disconnectedApiBaseInput.value.trim();
    if (val) {
      updateApiBase(val);
      disconnectedModal.classList.add('hidden');
    }
  });
}

if (dismissDisconnectedBtn) {
  dismissDisconnectedBtn.addEventListener('click', () => {
    disconnectedModal.classList.add('hidden');
  });
}

// App Startup
window.addEventListener('DOMContentLoaded', () => {
  lucide.createIcons();
  connectWebSocket();
  fetchStatus();
  fetchJobs();
  fetchSettings();
});
