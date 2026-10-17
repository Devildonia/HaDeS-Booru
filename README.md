# HaDeS Booru v1.0.0

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/Devildonia/HaDeS-Booru/actions/workflows/ci.yml/badge.svg)](https://github.com/Devildonia/HaDeS-Booru/actions/workflows/ci.yml)

Multi-source tag extractor, semantic prompt normalizer, and dataset utility built with Python 3.11 and Gradio.

## Features

- **Native HTTP Engine**: Requests and image downloads execute through Python (`httpx`) with domain-specific headers (`User-Agent` and `Referer`) and automatic backoff.
- **27 Supported Sources Across 7 API Families**:
  - **Danbooru v2**: `danbooru.donmai.us`, `safebooru.donmai.us`, `hijiribe.donmai.us`, `sonohara.donmai.us`, `aibooru.online`, `booru.allthefallen.moe`
  - **Gelbooru / DAPI**: `safebooru.org`, `gelbooru.com`, `rule34.xxx`, `rule34.us`, `tbib.org`, `xbooru.com`, `realbooru.com`
  - **Moebooru**: `konachan.com`, `konachan.net`, `yande.re`, `sakugabooru.com`, `lolibooru.moe`
  - **E621 / E926**: `e621.net`, `e926.net`
  - **Philomena**: `derpibooru.org`
  - **Zerochan**: `zerochan.net`
  - **Art Platforms & OpenGraph**: `deviantart.com` (RSS), `artstation.com`, `pawoo.net`, `e-hentai.org`, `booru.io`
- **Configurable Display Quality**: Switch between `Low (180p)`, `Medium (720p)`, `High (Sample HD, default)`, `Original (Uncompressed)`, and `Text Only`.
- **Semantic Tag Normalization**: Configurable category ordering (`copyright > character > artist > general > meta`), kaomoji preservation (`^_^`, `(o_o)`), underscore replacement, parenthesis escaping, and wildcard junk filtering.
- **Batch Dataset Export**: Export as consolidated `.txt` (1 prompt per line or unified tag block), `.zip` trainer caption archive, or write image + `<id>.txt` pairs directly to a local directory.
- **Bilingual Interface**: English (`en`, default) and Spanish (`es`), persisted in `config.local.json`.

## Screenshots

> Captured against **Safebooru** (safe-only source) — `hatsune_miku 1girl`, 20 results.

| Gallery & Inspector | Batch Export |
|---|---|
| ![Gallery & Inspector](docs/screenshots/01-gallery-search.png) | ![Batch Export](docs/screenshots/02-batch-export.png) |

**Normalization & API Keys**

![Normalization & API Keys](docs/screenshots/03-normalization.png)

## Project Structure

```text
HaDeS-Booru/
├── app.py                        # Entry point (http://127.0.0.1:7860)
├── start.bat                     # Windows launcher script
├── start.sh                      # Linux / macOS launcher script
├── requirements.txt              # Runtime dependencies
├── requirements-dev.txt          # Dev dependencies (pytest, ruff)
├── pyproject.toml                # Project metadata, Ruff and Pytest configuration
├── LICENSE                       # MIT license
├── hades_booru/                  # Core package
│   ├── models.py                 # Pydantic v2 domain models
│   ├── config.py                 # Persistent JSON configuration manager
│   ├── i18n.py                   # English and Spanish localization strings
│   ├── http_client.py            # HTTPX client with domain header routing
│   ├── image_cache.py            # Bounded disk image cache for gallery rendering
│   ├── normalizer.py             # Tag sanitizer and semantic prompt builder
│   ├── exporter.py               # TXT, ZIP, and local folder dataset writer
│   ├── demo_data.py              # Offline sample dataset
│   ├── adapters/                 # Source adapters and URL auto-detection registry
│   └── ui/                       # Gradio Blocks layout, HTML renderers, and theme
├── docs/screenshots/           # README screenshots (Safebooru, SFW)
└── tests/                        # Automated test suite (Pytest)
```

## Quick Start

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 2. Run the Application
- **Windows**: double-click `start.bat`
- **Linux / macOS**: `./start.sh`
- **Any OS**:
```bash
python app.py
```
The web interface listens on `http://127.0.0.1:7860` (local only by default).

> **Security note**: `python app.py --share` exposes the interface through a public Gradio tunnel. Avoid this flag if you have loaded personal API credentials.

### 3. Run Tests and Linter (development)
```bash
pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
```

## License

Distributed under the [MIT License](LICENSE).
