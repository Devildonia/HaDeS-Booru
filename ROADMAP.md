# Roadmap

Status of shipped milestones and architectural conventions, updated as of v1.1.0 (October 2026).

## Shipped Milestones

| Version | Highlights |
|---|---|
| v1.1.0 | Offline SQLite Tag Dictionary (`hades_booru/tag_dictionary/`) + CLI importer, selectable Dark/Light/System theme (WCAG AA >= 4.5:1) with locally bundled Inter & JetBrains Mono WOFF2 fonts (`R6-17`), per-session personal lists under `--share` (`X8` / `R6-12`), 3-layer DAPI tag categorization (`X9` / `R6-13`), shared `BooruAdapter.paginate()` (`R6-24`), modular UI split (`R6-25`), CI hardening (`R6-08`), Gradio 6.30 compatibility (telemetry off, gzip `iter_bytes`, Cloudflare challenge detection), command-deck stretch fix, 206 tests |
| v1.0.7 | Audit R6 hardening: Danbooru credential-leak host matching (High), SSRF guard, history/cache/config hardening, dependency audit (certifi, documented Pillow pin), 143 tests |
| v1.0.6 | Search history + top tags panel, default port 7863 with auto-fallback probe, drop-to-replace in Image to Prompt, pre-release audit hardening |
| v1.0.5 | Gallery Next/Prev selection fix, "Personal Tag List" renamed to "Blacklist" |
| v1.0.4 | Audit R4 fixes (X1–X7) |
| v1.0.3 | Personal tag blacklist/whitelist + Image to Prompt |
| v1.0.0–v1.0.2 | Core release cycle |

## Known Intentional Design Decisions

- **Rule34.us scraper rating (`R6-21`)**: rates scraped posts `e` (Explicit) conservatively because the HTML listing does not expose per-post rating metadata. Fails toward the safe side; do not alter without an authoritative rating source.
- **DAPI tag categorization residual edge cases (`X9`)**: while the 3-layer classifier (expanded parenthesized exemptions + offline Tag Dictionary batch lookup + optional `DapiTagCategoryCache`) resolves common false positives like `red_(color)` or `sitting_(pose)` and known artists/franchises, brand-new unindexed tags on DAPI boards that use ambiguous parenthesized qualifiers still fall back to `character` or `general`.

## Conventions

- Every version ships with: updated `pyproject.toml`, `hades_booru/__init__.py`, `README.md` header, and launchers (`start.bat` pure ASCII + CRLF, `start.sh`); full test suite green; `ruff` clean.
- Release notes live in `RELEASES.md` (newest first); the README links to it.
- Post-release fixes land on `master` without a release and are recorded in `RELEASES.md` under the affected version.
