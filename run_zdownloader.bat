@echo off
title Zdownloader - Local Engine
cd /d "%~dp0"

echo ===================================================
echo             Starting Zdownloader...
echo ===================================================

if not exist ".venv\Scripts\python.exe" (
    echo [Zdownloader] Setting up Python virtual environment...
    python -m venv .venv
    echo [Zdownloader] Installing dependencies from requirements.txt...
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
)

echo [Zdownloader] Starting agent and opening web interface...
.\.venv\Scripts\python.exe start.py
pause

