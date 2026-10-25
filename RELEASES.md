# Release Notes

Version-by-version history, design decisions, and release conventions for **HaDeS Booru**, newest first.
Current version, features, and quick start: see [README](README.md).

---

## v1.1.2

**Reliability & security follow-up release** — restores a v1.0.6-era behavior that regressed on Gradio 6.30 and closes every verified item of the R8 external audit (R8-A through R8-F).

**Fixed**

- **Drop-to-replace in Image to Prompt works again (regression)**: Gradio 6.30's Svelte File component shrinks its native drop zone to a 16 px corner icon as soon as a file is loaded, so dropping a new image on top of the existing one silently did nothing. A page-level script (wired through `launch(js=...)`, the Gradio 6 location for page JS) now extends the drop surface to the whole Image-to-Prompt tab and retargets file drops onto the upload button, whose handler and the newest-file-wins wiring already worked. Verified in a real browser (4 drop scenarios, extraction re-runs each drop) with three regression tests.
- **Credentials never leak across origins (R8-A, Medium-High, security)**: the manual redirect following added in R7-A passed the user's Basic-Auth on **every** hop, so a compromised board or an open redirect on a legitimate one would receive the API key — behavior httpx itself prevents with `follow_redirects=True`. Credentials now travel only to the original origin (scheme + host + normalized default port); any cross-origin redirect hop goes unauthenticated. Same-origin hops (e.g. path upgrades) keep their credentials. Two regression tests pin both cases.
- **Importer checkpoint no longer breaks `--resume` (R8-B, Medium)**: the 50-tag crash-safe checkpoint upserted **all** collected tags, including the not-yet-enriched tail; `resume` skips stored tags, so an interrupted import silently lost the rest forever. The checkpoint now persists only the tags already enriched, and the final upsert still covers everything. Regression test simulates a hard mid-import death (child process, `os._exit`) at tag 53 of 55 and asserts the tail is re-enriched — and actually recovered — on the next run.
- **System Status no longer clips long text (R8-D, Low)**: the compact command-row `max-height`/`overflow: hidden` rules (added to fix the Gradio 6.30 stretch chain) also clipped the status readout ("Query comple…"). The status block now opts out via a dedicated `hades-status-block` class; wrapped summaries and long URLs render in full. Browser-verified (`max-height: none`, zero clipping with a long payload).
- **Dependency hygiene (R8-C)**: `brotli` locked to 1.2.1 (fixes PYSEC-2026-4322 / GHSA-9v8h-qqgm-4m35 — it decodes remote `Content-Encoding: br` payloads); the two new Pillow 12.x advisory IDs join the documented, dated ignore list (still unfixable while Gradio 6 pins `pillow<13`). `pip-audit` on the locked set now reports **no known vulnerabilities**.
- **Error context restored (R8-F)**: the "payload that is not valid JSON" error carries the offending URL again.
- **Drift guard (R8-E)**: the two mirrored manual-redirect loops in `HttpClient` now cross-reference each other so a future edit cannot silently diverge them.

**Tests**

- 3 new regression tests (`tests/test_audit_r8.py`), 1 R7 test re-pinned to the corrected checkpoint semantics, `DummyClient` mock extended to record per-hop request attributes. **231 tests, all green; `ruff` clean; `mypy` clean (32 files); `pip-audit` clean (37 documented Pillow ignores).**

## v1.1.1

**Security-hardening & source-coverage release** — closes every verified item of the R7 external audit (R7-A through R7-H, with R7-F accepted and documented as a limitation) and adds a new Booru source with an explicit capability model.

**Security & Correctness (R7 audit fixes)**

- **Redirect SSRF guard actually fires now (R7-A, High)**: the old httpx event-hook guard could never run (httpx populates `response.next_request` only after the hook), so a `302` to `http://127.0.0.1` slipped past the SSRF block. `HttpClient` now follows redirects manually (`follow_redirects=False`, max 5 hops) and re-validates **every** hop with the public-host guard before the next request leaves the process. A hostile redirect chain raises a non-retryable error instead of leaking credentials or probing the LAN. Three regression tests cover the malicious hop, a legitimate public hop, and the hop cap.
- **Config merge no longer resurrects cleared state (R7-B)**: `ConfigManager.save()` now does a true 3-way field merge (base = snapshot at load, mine, disk) and re-bases the snapshot after each successful save. Consequences: reverting a scalar back to its loaded value works; an explicitly cleared list stays cleared; removing one item is not undone by the old union logic; session-only (`persist_credentials=False`) mode wipes exactly the entries this process touched and never another instance's; the cross-instance credential wipe (R7-01) and N5 clear contract both hold. Six scenario tests pin this behavior.
- **CI vulnerability review kept honest (R7-C)**: the `pip-audit` ignore list now covers all 35 known Pillow 12.x advisories with a dated review comment; a new test re-runs `pip-audit` and fails if any advisory is missing from the documented list, so the ignore list can never silently rot.
- **Test suite is hermetic (R7-D)**: a new autouse `tests/conftest.py` fixture fakes DNS resolution (IP literals resolve to themselves, hostnames to a fixed public IP), so the SSRF tests and every guard path run identically online or offline. No more `Could not resolve host: example.com` flakes on machines without network.
- **Long text no longer overflows the UI (R7-E)**: navigation badges and status boxes wrap instead of clipping/overflowing (`min-width: 0`, `overflow-wrap: anywhere`, `white-space: normal`), fixing the deformed Limit/Rating columns reported in the v1.1.0 review.
- **Image cache is byte-bounded (R7-G)**: `DiskImageCache` now enforces `max_bytes` (default 4 GiB) in addition to the file-count cap — pruning oldest-first by either dimension — closing the theoretical ~300 GiB disk exposure of the count-only cap.
- **Importer survives a dropped connection (R7-H)**: a failed tag-list page no longer aborts the whole import; the collector logs and continues with the partial catalog, and enrichment progress is upserted in idempotent 50-tag checkpoints so a crash (or Ctrl-C) mid-import keeps everything already enriched.
- **R7-F (accepted limitation, documented)**: DNS-rebinding between the guard's lookup and httpx's connect is documented in `assert_public_host`; IP-pinned connections judged disproportionate for this app's threat model.

**New Features**

- **Furbooru source (Philomena family)**: `furbooru.org` is now a first-class source (28 total, 7 families), using the existing anonymous Philomena JSON API (`/api/v1/json/search/images`), exact-host URL detection, and the shared pagination engine. Verified live (HTTP 200 JSON, ~398k images) before registration.
- **Source capability metadata**: `BooruSourceSpec` gains `api_family`, `auth_required`, `supports_tags`, `supports_rating_filter`, and `status` (all backward-compatible with safe defaults), so the catalog now records *what* each source supports — Furbooru is the first entry registered with the full model; a full catalog pass lands in a later v1.1.x release. E-Shuushuu was investigated and deferred: its search endpoint responds anonymously, but the posts endpoint could not be verified without an API key, so shipping it unverified would break the no-broken-sources policy.

**Tests**

- 13 new regression tests in `tests/test_audit_r7_round2.py` (redirect guard, 3-way merge scenarios, CSS wrapping, byte pruning, importer partial + checkpoints, CI ignore-list parity, Furbooru metadata) plus the hermetic DNS fixture. **225 tests, all green; `ruff` clean; `mypy` clean (32 files).**

## v1.1.0

**Major feature & architectural release** — closes every item on the v1.1.0 roadmap: offline SQLite Tag Dictionary, selectable Light/Dark/System theme with locally bundled fonts, per-session personal lists under `--share`, 3-layer DAPI tag categorization, shared adapter pagination (`R6-24`), modular UI package split (`R6-25`), and CI hardening (`R6-08`).

**New Features**

- **Offline Tag Dictionary (§1)**: new `hades_booru/tag_dictionary/` package backed by a local SQLite catalog (`tags.sqlite3`, auto-seeded on first query with 38 curated foundational tags and 75 common aliases, gitignored) plus a resumable, rate-limited, fault-isolated CLI importer (`python -m hades_booru.tag_dictionary.importer --top 1000`) that grows the catalog to the 1,000 most popular Danbooru tags (`--resume` / `--no-resume` / `--skip-wiki`) without blocking app startup, cleaning DText wiki markup (including template-macro stripping) as it imports. Exact-match and alias lookups (`miku` -> `hatsune_miku`, `1_girl` -> `1girl`) resolve in sub-millisecond time. Bilingual support follows strict rules: original English definitions are always stored as-is, and Spanish definitions are shown only when a genuine translation exists (never auto-translated). Exposed in a new **Tag Dictionary** (`Diccionario de Tags`) tab with quick-tag chips, Danbooru wiki links, and a live indicator of how many tags are available in the local catalog.
- **Selectable Light / Dark / System Theme & Offline Fonts (§4, R6-17)**: added `ThemeMode` (`dark`, `light`, `system`) to `AppConfig`, persisted in `config.local.json` and switchable live from the top bar. Both Dark (`#0B0D13` canvas) and Light (`#F8FAFC` canvas) palettes are defined via semantic CSS custom properties with verified WCAG AA contrast ($\ge 4.5:1$) across all text tokens and category badges. `System (Auto)` honors `prefers-color-scheme` on load and reacts live to OS theme switches. `Inter` and `JetBrains Mono` WOFF2 fonts (plus `OFL.txt`) are bundled locally under `hades_booru/ui/assets/fonts/` and served via `@font-face` data URIs, eliminating external `fonts.googleapis.com` requests.
- **Per-Session Personal Lists under `--share` (§2 / X8 / R6-12)**: new `SessionLists` and `PersonalListStore` in `hades_booru/ui/state.py`. When launched with `python app.py --share`, personal blacklist, whitelist, and default junk overrides live exclusively in per-session `gr.State` so remote visitors cannot see or mutate the host's `config.local.json` or each other's lists. Local (non-share) mode preserves full disk persistence.
- **3-Layer DAPI Tag Categorization (§3 / X9 / R6-13)**: `GelbooruAdapter._categorize_dapi_tags` now classifies flat Gelbooru/DAPI tags through three layers:
  1. Expanded suffix heuristics with explicit general exemptions (`_(color)`, `_(pose)`, `_(position)`, `_(style)`, `_(clothing)`, `_(attire)`, `_(outfit)`, `_(expression)`, `_(emotion)`, `_(object)`, `_(weapon)`, `_(food)`, `_(vehicle)`, `_(animal)`, `_(creature)`, `_(background)`, `_(lighting)`, `_(framing)`, `_(focus)`, `_(count)`, `_(meme)`, `_(parody)`, `_(voice_actor)`, `_(seiyuu)`), `_(artist)` / `drawn_by_*` -> `artist`, and franchise suffixes -> `copyright`.
  2. Single-query SQLite batch lookup (`TagDictionaryService.batch_categories`) for non-parenthesized `artist`, `copyright`, and `character` tags.
  3. Optional thread-safe LRU cache (`DapiTagCategoryCache`) for the DAPI `s=tag&q=index` endpoint. New, unindexed DAPI tags with ambiguous parenthesized qualifiers intentionally fall back to `character`/`general` (documented limitation, not a bug).

**Architecture & CI Hardening**

- **Shared Adapter Pagination (`R6-24`)**: extracted `BooruAdapter.paginate()` into `hades_booru/adapters/base.py`, removing 6 duplicated pagination loops across `danbooru`, `gelbooru`, `e621`, `moebooru`, `philomena`, and `zerochan` while preserving each family's specific stop condition and partial-result warning behavior.
- **Modular UI Package (`R6-25`)**: split `hades_booru/ui/layout.py` into focused modules (`state.py`, `desktop.py`, `handlers.py`, `layout.py`, `components.py`, `theme.py`) and removed hardcoded inline hex colors from `components.py` in favor of semantic CSS classes.
- **CI Hardening (`R6-08`)**: `.github/workflows/ci.yml` now pins GitHub Actions to full commit SHAs (`actions/checkout@11bd7190...`, `actions/setup-python@a26af69b...`), adds Python `3.13` to the OS/version matrix, adds dedicated `mypy` typecheck and `pytest-cov` (`--cov-fail-under=80`) jobs, and runs `pip-audit` on a weekly cron schedule (`0 6 * * 1`).
- **Tests**: new coverage across 5 test modules (`test_paginate_refactor.py`, `test_tag_dictionary.py`, `test_session_personal_lists.py`, `test_dapi_categorization.py`, `test_theme_and_ui_overhaul.py`), including the resumable importer and the dictionary count-line rendering. **212 tests, all green; `ruff` clean; `mypy` clean (32 files).**

## v1.0.7

**Post-release audit (R6) hardening** — the most exhaustive audit of the codebase so far (static analysis, real-browser E2E, dependency audit, coverage). 1 High + 6 Medium + 20 Low findings; all High/Medium and the practical Lows are fixed here; the remainder are accepted as documented, low-impact limitations.

**Security (High + Medium)**

- **Danbooru credential-leak fix (R6-01, High — existed since v1.0.0)**: `can_handle_url` matched the board's domain as a *substring of the whole URL* (query included), so a crafted link like `https://danbooru.donmai.us.evil.example/posts/1` was treated as Danbooru and your Basic-Auth user + API key were sent to the attacker's host. All 7 adapters now use exact host matching (`host == domain` or `*.domain`), and Danbooru's fetch-by-URL additionally pins the API call to its own domain as defense in depth. Three malicious-URL regression tests keep it closed.
- **SSRF / private-network guard (R6-04)**: requests to loopback, private, reserved or link-local addresses are now blocked — including on every redirect hop — and network errors no longer echo the response body into the UI (only status code + host). Matters when the app is exposed via `--share` / `--host 0.0.0.0`. Override with `HADES_ALLOW_PRIVATE_HOSTS=1` for a self-hosted LAN board.
- **Search-history credential scrub (R6-05)**: pasted URLs saved to the history now have sensitive query parameters stripped (`api_key`, `key`, `token`, `password`, `login`, `user_id`, …) — not only `user:pass@`. Pasting a full API URL no longer writes a plaintext key to `config.local.json`.
- **Image-cache poisoning (R6-06)**: a `200 text/html` response (e.g. a Cloudflare page) served from a `.jpg` URL is no longer stored and re-served on every later search. Downloads are validated with magic bytes before being cached, and already-poisoned cache entries are detected, deleted and re-downloaded.
- **Multi-instance config safety (R6-07)**: since the v1.0.6 port auto-fallback, running two instances from the same folder works — and their `config.local.json` saves no longer clobber each other. Saves take a `filelock`, re-read the file and merge, so history, blacklist and language are preserved across instances.

**Robustness (Medium + practical Low)**

- **Image-to-Prompt parser surface (R6-03/14)**: files are now opened with `Image.open(path, formats=["PNG", "JPEG", "WEBP"])` — a GIF renamed `.png` is rejected *before* Pillow's GIF plugin parses it; `MAX_IMAGE_PIXELS` is set explicitly (64 MP) and `DecompressionBombError` becomes a friendly status instead of a raw exception.
- **Response size caps (R6-20)**: JSON/XML bodies are capped at 16 MiB and media downloads at 512 MiB (streamed, not buffered whole), so a hostile `file_url` cannot exhaust memory.
- **Rating-flag residual (R6-09)**: the thread-local `server_rating_applied` flag is reset before the fetch-by-URL path, so a "General" selection no longer skips the client-side filter for a pasted post after an earlier safe-rated search.
- **`javascript:` hrefs (R6-10)**: source links in the UI only accept `http(s)://` URLs — anything else renders inert (`#`).
- **ZIP error state (R6-11)**: `last_zip_errors` is reset at the start of each export, so concurrent exports no longer mix each other's warnings.
- **Folder dialog (R6-15)**: native-dialog failures are logged instead of being silently swallowed.
- **Dark theme (R6-18)**: the app now forces Gradio's dark mode — the custom palette is dark-only, and light mode left section headers nearly invisible (contrast 1.05:1 vs the 4.5:1 WCAG AA minimum).
- **Windows launcher (R6-19)**: `start.bat` now does `cd /d "%~dp0"`, so a shortcut with a different working directory no longer makes `config.local.json` / `.cache` / `exports` point at the wrong folder.
- **Export filenames (R6-22)**: ZIP/TXT names now include the time (`%Y-%m-%d_%H%M`) and get a `_2` / `_3` suffix on collision — two exports on the same day no longer overwrite each other.
- **Magic-first extensions (R6-23)**: the stored file extension follows the actual byte signature before the URL's extension, so a CDN serving WebP from a `.jpg` URL is stored with the right extension.
- **Config schema (R6-26)**: `AppConfig` now carries `schema_version` (1), preparing for future schema migrations instead of a silent full reset.

**Dependencies (R6-02)**

- `certifi` updated to `2026.10.19` (fixes PYSEC-2026-4320); `requirements.lock` regenerated from a clean venv.
- **Honest Pillow note**: Pillow is pinned to `12.3.0` — the latest release installable alongside Gradio 6.x, which hard-pins `pillow<13`. Pillow 13.0.0 fixes 24 known CVEs, but with 13.x a fresh `pip install -r requirements.txt` fails dependency resolution, so installability wins. Practical impact here is limited (Pillow only parses local, user-provided image files, and the R6-03 fix already restricts which parsers can run). The 24 CVEs are documented and explicitly ignored in the CI `pip-audit` job with that justification — to be removed as soon as Gradio supports Pillow 13.

**Tests**

- 18 new regression tests (`tests/test_audit_r6.py`): malicious-URL rejection by every adapter, GIF-as-PNG rejection, SSRF guard + env override, history query scrub, poisoned-cache recovery, multi-instance config merge, rating-flag reset, `javascript:` href, ZIP-error reset, launcher `cd /d`, timestamped filenames with collision suffix, magic-first extension, `schema_version`.
- Shared streaming HTTP mocks extracted to `tests/http_mocks.py`. **143 tests, all green; `ruff` clean; CI `pip-audit` command verified passing.**

**Deferred to v1.1.0** (now shipped in the v1.1.0 release above): CI hardening (R6-08), local font bundling (R6-17), pagination dedup (R6-24), `layout.py` split (R6-25). The Rule34.us scraper rating is intentionally conservative (R6-21) — documented as a known limitation, not a bug.

## v1.0.6

**Quality of life**

- **Recent searches + Top tags (side by side)**: the search area now keeps your last 12 queries (deduplicated, most-recent-first) in a **Recent searches** dropdown — pick one to drop it straight into the Search-tags bar (press Search / Enter to run it), or **Clear** to wipe the stored history without touching the search bar. Beside it, a **Top tags** picker lists your most-reused individual tags (derived from the same history); **Add** appends one to the Search-tags bar (deduplicated, no auto-run) so you can build tag queries faster. History is persisted in `config.local.json` and only successful searches are recorded — failed queries are not pinned.
- **Sensible default port + auto-fallback**: the default port moved from `7860` to `7863` so it no longer collides with Stable Diffusion WebUI / Forge (`7860` / `7861`) or ComfyUI (`8188`). If the requested port is busy, the launcher probes the next ports (up to 50 tries) and binds the first free one, then prints the chosen URL — the app always launches. `--port` is still honored for an explicit override.
- **Drop-to-replace in Image to Prompt**: you can now drag a new image into the Extract tab even when one is already loaded — the drop zone stays visible and the newest file wins. A new **Clear Image** button resets the file, preview, and all extracted sections at once.
- **New tests**: regression coverage for search-history recording (dedup / cap / empty / ignore-on-failure), the recent-searches dropdown wiring and clear handler, top-tags ranking / cap / append-dedup, the extract drop-to-replace `[-1]` selection, and the language-switch relabels for all new controls. `ruff` clean.

**Pre-release audit hardening** (final full-project audit, all findings closed before push)

- Gallery image download failures are now logged at debug level (post id + URL) instead of being swallowed silently — the placeholder-card fallback behavior is unchanged.
- The port probe is now race-safe in practice: if the OS still refuses the bind (port snatched between probe and launch), the launcher prints a clear, actionable error and exits cleanly instead of dumping a low-level traceback.
- The Top-tags picker always resets its selection after a search or a Clear, so it can never hold a stale tag that dropped out of the refreshed list.
- The Recent searches dropdown is now selection-only (no free-text typing) — free text belongs in the Search-tags bar; the dropdown strictly picks from recorded history.

**Post-release audit (R5) hardening** (fixed immediately after the v1.0.6 tag)

- **Rating filter safety (Danbooru)**: when the board rejects the rating tag with HTTP 422 and the adapter falls back to a plain query, the client-side rating filter is now re-armed instead of being skipped — selecting "General" can no longer surface explicit posts after that fallback.
- **Thread-safe rating flag**: the server-side rating flag is now thread-local (same mechanism as the partial-result warning), so concurrent searches with different ratings can no longer leak each other's filter state. The thread-local storage also uses identity-checked entries, closing an object-id reuse hazard (this hardens `last_warning` as well).
- **ComfyUI extraction**: orphaned (unlinked) text nodes are now discarded instead of being mixed into the negative prompt, so positive-side words can no longer pollute what users train against.
- **Port probe**: the probe no longer uses `SO_REUSEADDR` — on Windows that flag could let the probe "bind" a port a listener already holds and falsely report it as free, defeating the auto-fallback.
- **History privacy**: pasted URLs saved to the search history have any embedded `user:pass@` credentials stripped before persistence.

## v1.0.5

**Fixes & naming (follow-up to v1.0.4)**

- **Gallery navigation fix (Next/Previous)**: the Previous/Next buttons in Gallery & Inspector now move the selected image in the gallery, not just the prompt and inspector panels. The fix moves the gallery selection through Gradio 6's `selected_index` prop, so the highlighted thumbnail, the preview modal, and the inspector all stay in sync.
- **Tab rename**: the "Personal Tag List" tab is now simply called **Blacklist** (ES: **Lista Negra**), matching the terminology already used inside the panel. The panel heading was renamed accordingly in both languages. No behavior change.
- **New tests**: 6 regression tests for the navigation fix (arity on both return paths, selection index per direction, prompt follows the selected post). 100 tests, all green; `ruff` clean.

## v1.0.4

**External audit (R4) fixes — Image to Prompt correctness + rating filter**

- **A1111 multi-line split (X1)**: `Steps: N` (and the rest of the settings line) no longer leaks into the Negative Prompt box; the settings block is now detected when it starts on its own line, with or without a `Negative prompt:` marker.
- **EXIF `UNICODE` comments (X2)**: JPEG/WebP comments written by A1111 (UTF-16 with `UNICODE` prefix) decode correctly instead of producing `\x00`-garbled tags; `ASCII` prefix padding NULs no longer leak into the text.
- **PNG XMP support (X3)**: XMP blobs stored under Pillow's `XML:com.adobe.xmp` key (the PNG location) are now read, and both `<dc:term>` and `<rdf:li>` subject forms are parsed.
- **ComfyUI prompt graphs (X4)**: positive/negative are resolved by following the sampler node's `positive`/`negative` links instead of node-id order (which was lexicographic), so graphs with non-consecutive or inverted node ids no longer swap or misassign sections; unlinked text nodes are preserved.
- **Whitelist semantics (X5)**: whitelist entries without `*` now match exactly (previously `solo` also kept `solo_focus`, `soloist`, ...); wildcards work as before.
- **Tag counter scope (X6)**: the success counter and tag chips only count positive tags — negative words and settings no longer inflate them.
- **e621 "General" rating (X7)**: adapters now report when the rating filter was applied server-side and the UI skips its client-side re-filter, so a "General" selection on e621 no longer returns zero results (its safe bucket is rated `s`).
- **New tests**: 16 regression tests covering every fixed case (`tests/test_metadata_extractor.py`, `tests/test_normalizer.py`, new `tests/test_audit_r4_adapters.py`).
- 94 tests, all green; `ruff` clean.

## v1.0.3

**Personal tag filtering + Image to Prompt**

- **Personal tag blacklist**: extend the default excluded-tag list with your own tags (comma or newline separated, `*` wildcard supported) from a dedicated panel in the Normalization tab. Entries are persisted in `config.local.json` and "Reset Default Excluded Tags" no longer wipes your personal list.
- **Personal tag whitelist**: force-keep tags that would otherwise be filtered (e.g. `commission`), even if they appear in the defaults or your blacklist. Wildcards supported.
- **One-click post blacklist**: from the Inspector dock, a new button adds every currently-filtered tag of the selected post to your personal blacklist at once.
- **Image to Prompt (new tab)**: drag & drop a PNG/JPEG/WebP and its embedded data is extracted **automatically on drop, 100% locally** — Stable Diffusion / A1111 `parameters`, ComfyUI prompt graphs (decoded from JSON), booru `comment` tEXt chunks (e.g. Bilibili), NovelAI-style `prompt` chunks, Civitai XMP, and JPEG/WebP EXIF `UserComment`. The result is presented in **three dedicated copyable boxes: Positive Prompt, Negative Prompt, and Generation Settings** (one key per line). Positive and negative pass through your active normalizer (trigger word prefix on the positive only, blacklist/whitelist included); the tags render as inspector-style chips. Images without metadata produce a clear explanatory status instead of a silent failure.
- **Windows launcher fix**: `start.bat` is now pure ASCII with CRLF line endings. No more `"LORA" no se reconoce como un comando` error (an unescaped `&` in the title line split it into a second command) and no more `ÔÇç` mojibake (UTF-8 em-dash under the cp850 console code page). A regression test keeps the launcher ASCII-safe.
- **Pre-release audit**: three runtime wiring mismatches fixed before publication — the language-switch handler returned 81 values for 80 outputs (Extract-section labels landed on the wrong boxes), the metadata error path returned 4 values for 6 outputs (a browser-side crash instead of the error status), and the empty personal-tag input returned 2 values for 7 outputs. New `tests/test_ui_wiring_counts.py` (11 runtime wiring tests) invokes the real handlers and verifies return arity plus component-by-component alignment, so this class of regression can never pass again.
- **i18n**: full EN/ES coverage of all new UI strings.
- 77 tests, all green; `pip-audit` clean in CI.

## v1.0.2

**Fixes & hardening (follow-up to v1.0.1)**

- **Server-side rating filter refinements**: Danbooru v2 boards now respect the anonymous 2-tag limit (the rating metatag is only injected when safe, with an automatic HTTP 422 fallback), Moebooru boards use their canonical `rating:safe`/`questionable`/`explicit` metatags, and E621/E926 use `rating:s|q|e` metatags with E926 SFW rating normalization.
- **Credential security & management**: saved credentials use generic masked placeholders so neither `user_id` nor `api_key` values are serialized into Gradio's `/config` payload, plus a new action to clear saved credentials from memory and disk.
- **Thread-safe adapter warnings & bounded retry**: `BooruAdapter.last_warning` is isolated per thread via `threading.local()`, and HTTP 429 `Retry-After` waits are capped at 30 seconds.
- **Cross-platform fix**: "open folder in explorer" on macOS/Linux no longer crashes (an invalid `check=` kwarg was passed to `subprocess.Popen`, which only `subprocess.run` accepts).
- **Normalizer & taxonomy**: `exclude_categories` now filters `raw_tags`-only posts (Zerochan, Art Platforms), Gelbooru franchise suffixes (`_(series)`, `_(game)`, etc.) and `_(cosplay)` are categorized accurately, and multi-tag Pawoo queries notify when truncated to the first hashtag.
- **i18n**: restored the Spanish "o" in the search placeholder (it had regressed to the English "or").
- Test suite grows to 46 tests.

## v1.0.1

**New features**

- **Server-side rating filter**: when you pick a rating (G/S/Q/E), the query is now sent to the source API where it is supported — Danbooru v2 boards (`rating:safe`/`sensitive`/`questionable`/`explicit` tags), Moebooru boards (`rating` parameter), E621/E926 (`rating[]` parameter), and DAPI boards (`rating:s|q|e` tags) — instead of downloading everything and filtering locally. Sources without server-side support keep the client-side safety filter, and "Unrated" (which no API can pre-filter) always falls back to it.
- **Locked, auditable dependencies**: `requirements.lock` pins the full dependency tree for reproducible installs, and CI now runs `pip-audit` against it on every push.
- Test suite grows to 39 tests.

## v1.0.0

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

---

## Release Conventions

- Every version ships with: updated `pyproject.toml`, `hades_booru/__init__.py`, `README.md` header, and launchers (`start.bat` pure ASCII + CRLF, `start.sh`); full test suite green; `ruff` and `mypy` clean.
- Release notes live in this file (newest first); the `README` links to it.
- Post-release fixes land on `master` without a new release and are recorded under the affected version.
