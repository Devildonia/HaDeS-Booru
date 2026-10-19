# HaDeS Booru v1.0.3

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
├── requirements.txt              # Runtime dependencies (range pins)
├── requirements.lock             # Locked dependency tree (reproducible installs, pip-audit in CI)
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

For a fully reproducible install with the exact audited dependency tree:

```powershell
pip install -r requirements.lock
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

## Release Notes — v1.0.3

**Personal tag filtering + Image to Prompt**

- **Personal tag blacklist**: extend the default excluded-tag list with your own tags (comma or newline separated, `*` wildcard supported) from a dedicated panel in the Normalization tab. Entries are persisted in `config.local.json` and "Reset Default Excluded Tags" no longer wipes your personal list.
- **Personal tag whitelist**: force-keep tags that would otherwise be filtered (e.g. `commission`), even if they appear in the defaults or your blacklist. Wildcards supported.
- **One-click post blacklist**: from the Inspector dock, a new button adds every currently-filtered tag of the selected post to your personal blacklist at once.
- **Image to Prompt (new tab)**: drag & drop a PNG/JPEG/WebP and its embedded data is extracted **automatically on drop, 100% locally** — Stable Diffusion / A1111 `parameters`, ComfyUI prompt graphs (decoded from JSON), booru `comment` tEXt chunks (e.g. Bilibili), NovelAI-style `prompt` chunks, Civitai XMP, and JPEG/WebP EXIF `UserComment`. The result is presented in **three dedicated copyable boxes: Positive Prompt, Negative Prompt, and Generation Settings** (one key per line). Positive and negative pass through your active normalizer (trigger word prefix on the positive only, blacklist/whitelist included); the tags render as inspector-style chips. Images without metadata produce a clear explanatory status instead of a silent failure.
- **Windows launcher fix**: `start.bat` is now pure ASCII with CRLF line endings. No more `"LORA" no se reconoce como un comando` error (an unescaped `&` in the title line split it into a second command) and no more `ÔÇç` mojibake (UTF-8 em-dash under the cp850 console code page). A regression test keeps the launcher ASCII-safe.
- **Pre-release audit**: three runtime wiring mismatches fixed before publication — the language-switch handler returned 81 values for 80 outputs (Extract-section labels landed on the wrong boxes), the metadata error path returned 4 values for 6 outputs (a browser-side crash instead of the error status), and the empty personal-tag input returned 2 values for 7 outputs. New `tests/test_ui_wiring_counts.py` (11 runtime wiring tests) invokes the real handlers and verifies return arity plus component-by-component alignment, so this class of regression can never pass again.
- **i18n**: full EN/ES coverage of all new UI strings.
- 77 tests, all green; `pip-audit` clean in CI.

## Release Notes — v1.0.2

**Fixes & hardening (follow-up to v1.0.1)**

- **Server-side rating filter refinements**: Danbooru v2 boards now respect the anonymous 2-tag limit (the rating metatag is only injected when safe, with an automatic HTTP 422 fallback), Moebooru boards use their canonical `rating:safe`/`questionable`/`explicit` metatags, and E621/E926 use `rating:s|q|e` metatags with E926 SFW rating normalization.
- **Credential security & management**: saved credentials use generic masked placeholders so neither `user_id` nor `api_key` values are serialized into Gradio's `/config` payload, plus a new action to clear saved credentials from memory and disk.
- **Thread-safe adapter warnings & bounded retry**: `BooruAdapter.last_warning` is isolated per thread via `threading.local()`, and HTTP 429 `Retry-After` waits are capped at 30 seconds.
- **Cross-platform fix**: "open folder in explorer" on macOS/Linux no longer crashes (an invalid `check=` kwarg was passed to `subprocess.Popen`, which only `subprocess.run` accepts).
- **Normalizer & taxonomy**: `exclude_categories` now filters `raw_tags`-only posts (Zerochan, Art Platforms), Gelbooru franchise suffixes (`_(series)`, `_(game)`, etc.) and `_(cosplay)` are categorized accurately, and multi-tag Pawoo queries notify when truncated to the first hashtag.
- **i18n**: restored the Spanish "o" in the search placeholder (it had regressed to the English "or").
- Test suite grows to 46 tests.

## Release Notes — v1.0.1

**New features**

- **Server-side rating filter**: when you pick a rating (G/S/Q/E), the query is now sent to the source API where it is supported — Danbooru v2 boards (`rating:safe`/`sensitive`/`questionable`/`explicit` tags), Moebooru boards (`rating` parameter), E621/E926 (`rating[]` parameter), and DAPI boards (`rating:s|q|e` tags) — instead of downloading everything and filtering locally. Sources without server-side support keep the client-side safety filter, and "Unrated" (which no API can pre-filter) always falls back to it.
- **Locked, auditable dependencies**: `requirements.lock` pins the full dependency tree for reproducible installs, and CI now runs `pip-audit` against it on every push.
- Test suite grows to 39 tests.

## Release Notes — v1.0.0

**Bug fixes over development builds**

- API credentials are bound to the exact board they were entered for: mirrors (e.g. `safebooru.donmai.us`) no longer inherit `danbooru.donmai.us` credentials.
- Saving the credentials form no longer wipes boards whose fields were left empty.
- Partial search results (e.g. a failure on page 2 of 3) are kept and clearly flagged in the status bar instead of failing silently.
- ZIP trainer export writes an `errors.txt` manifest when individual image downloads fail, sanitizes entry names to a safe character set, and reports failures in the status bar.
- Export destination falls back to `./exports` when the requested folder is not accessible by the web server.
- The HTTP engine reuses a single connection pool per request sequence and honors the server's `Retry-After` header on HTTP 429.
- Kaomoji detection now accepts pipe characters (`(|_|)`, `(o|_o)`); Art Platform metadata is HTML-unescaped and URL-resolved; "open folder in explorer" works on Windows, Linux and macOS.
- Moebooru posts rated `g` are no longer mis-mapped to "unrated".
- `gradio` is pinned to the `6.x` major line.

## License

Distributed under the [MIT License](LICENSE).
