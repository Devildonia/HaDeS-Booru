# Roadmap

Status of deferred work, recorded as of v1.0.7 + post-release audit R6 hardening (October 2026).

## v1.0.x — Shipped

| Version | Highlights |
|---|---|
| v1.0.7 | Audit R6 hardening: Danbooru credential-leak host matching (High), SSRF guard, history/cache/config hardening, dependency audit (certifi, documented Pillow pin), 143 tests |
| v1.0.6 | Search history + top tags panel, default port 7863 with auto-fallback probe, drop-to-replace in Image to Prompt, pre-release audit hardening |
| v1.0.5 | Gallery Next/Prev selection fix, "Personal Tag List" renamed to "Blacklist" |
| v1.0.4 | Audit R4 fixes (X1–X7) |
| v1.0.3 | Personal tag blacklist/whitelist + Image to Prompt |
| v1.0.0–v1.0.2 | Core release cycle |

## v1.1.0 — Planned (major)

### 1. Tag Dictionary (flagship feature)

Local dictionary of Danbooru tag definitions with offline lookup.

- **Module layout** (`hades_booru/tag_dictionary/`):
  - `__init__.py` — public interface
  - `service.py` — exact-match search and alias resolution
  - `importer.py` — one-off catalog import/update (downloads tag list, aliases, and wiki definitions from the Danbooru API; never runs inside the app at startup)
  - `data/tags.sqlite3` — local SQLite catalog (gitignored)
- **Behavior**:
  - Exact tag search returns the stored definition in milliseconds, fully offline after import.
  - Alias resolution: searching an alias returns the canonical tag and its definition.
  - Bilingual: original (EN) definition stored as-is; Spanish translation stored only when a genuine translation is available — never auto-translated and presented as official.
- **UI**: new "Tag Dictionary" tab — search field, category, definition, aliases, and a source link back to the Danbooru wiki page.
- **Tests**: existing tags, aliases, unknown entries, special characters, both languages.
- **Design constraint**: the Gradio layer consumes the service; dictionary logic stays out of the UI components.

### 2. Per-session personal lists under `--share` (limitation X8)

**Current state**: the Blacklist / whitelist / junk lists live in `config.local.json` (`AppConfig`) and are global. Fine for local single-user use, but with `gradio --share` every remote user sees and mutates the same lists.

**Planned fix**:
- When the app is launched with `--share`, keep personal lists in per-session `gr.State` (in-memory only).
- In local (non-share) mode, keep the current disk-persisted behavior.
- Rewire all Blacklist panel handlers to a session-scoped store with a local-disk fallback.

**Effort**: medium (touches the whole Blacklist panel wiring). Deferred because ROI is low for the primary local workflow.

### 3. Better DAPI tag categorization (limitation X9)

**Current state**: Gelbooru/DAPI returns flat tags without categories, so the adapter guesses: `_(series)` → copyright, `_(cosplay)` → general, any `tag_(...)` → character, everything else → general. The `_(` → character rule is coarse (e.g. `red_(color)` is misfiled as character). This affects semantic ordering, category-based exclusion, and the Inspector view.

**Planned fix (options)**:
- Refine the suffix heuristics with explicit exemption lists (color, count, position, etc.).
- Per-board tag-category resolution via the DAPI tags endpoint (extra latency per unique tag; cache aggressively).
- No uniform guarantee is possible — document residual edge cases in the README.

**Effort**: medium-large. Deferred to v1.1.0 where it can be designed alongside the importer/infrastructure work.

### 4. Audit R6 deferrals (low ROI now, or design work)

Recorded from the R6 audit (October 2026); the fixes themselves shipped in v1.0.7.

| ID | Item | Why deferred |
|---|---|---|
| R6-08 | CI hardening: pin actions to commit SHAs, add a `mypy` job, Python 3.13 in the matrix, coverage job, weekly `pip-audit` cron | CI hygiene; no runtime impact. Batch with the v1.1.0 infra work. |
| R6-17 | Bundle Inter / JetBrains Mono locally (currently `gr.themes.GoogleFont` → browser fetches from `fonts.googleapis.com`) | Offline-purist improvement; needs font subsetting + licensing pass. |
| R6-24 | Extract a shared `paginate()` helper into `BooruAdapter` (the loop is duplicated 6×: danbooru, gelbooru, e621, moebooru, philomena, zerochan) | Structural refactor; every past fix (R5-Y1, R6-09) had to be applied 6 times. Do with tests around each adapter's quirk. |
| R6-25 | Split `layout.py` (2 178 lines, ~48 closures) into smaller modules | Maintainability; largest single refactor on the list. |

Related mappings: R6-12 → limitation X8 (§2) and R6-13 → limitation X9 (§3) — already tracked above.

## Explicitly out of scope for v1.1.0

- Y6 (browser verification of the v1.0.5 gallery fix) — closed by manual user verification; no action.
- R6-21 (Rule34.us scraper rates every post `e`) — **intentional**, fails toward the safe side. Documented as a known limitation, not a bug; do not "fix" without a real rating source.

## Conventions

- Every version ships with: updated `pyproject.toml`, `hades_booru/__init__.py`, README header, and launchers; full test suite green; `ruff` clean.
- Post-release fixes land on `master` without a release and are recorded in the README "Release Notes" of the affected version.
