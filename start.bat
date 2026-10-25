@echo off
cd /d "%~dp0"
title HaDeS Booru - Prompt Harvester + LoRA Dataset Builder
echo ============================================================================
echo   HaDeS Booru v1.1.2 - Python 3.11 + Gradio (Zero CORS Engine)
echo ============================================================================
echo Starting local server on http://127.0.0.1:7863 (auto-increments if busy) ...
python app.py
pause
