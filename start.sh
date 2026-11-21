#!/bin/sh
# HaDeS Booru v1.1.2 — launcher (Linux / macOS)
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1

echo "============================================================================"
echo "  HaDeS Booru v1.1.2 — Python 3.11 + Gradio (Zero CORS Engine)"
echo "============================================================================"
echo "Starting local server on http://127.0.0.1:7863 (auto-increments if busy) ..."
python app.py
