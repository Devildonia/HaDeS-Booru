# Roadmap

Forward-looking plan for **HaDeS Booru**, in addition to the completed history in [RELEASES.md](RELEASES.md).
Items are listed newest first; each entry states the target release and its status.

---

## v1.1.2 / v1.2.0 — Candidate Booru sources (researched, not yet integrated)

Ten candidate sources were researched by cross-referencing the current registry (28 sources, 7 API families) with public Booru catalogs (gallery-dl site list, AtlasTheBot/booru catalog) and third-party integrations.

**Policy reminder:** a source is only shipped after its endpoints are verified live and anonymously (or with the documented auth model), and after its `api_family` metadata is recorded. Unverified candidates stay in this list rather than shipping broken.

| Source | URL | Family / integration path | What to verify before integrating | Status |
|---|---|---|---|---|
| **Booruvar** | `booru.borvar.art` | Danbooru | Endpoint shape (`/posts.json` v2), rating filter, rate limits. High priority — reported compatible with standard Danbooru search. | Candidate |
| **Ponybooru** | `ponybooru.org` | Danbooru (or Moebooru) | Site availability today; API endpoint compatibility; anonymous access. | Candidate |
| **Twibooru** | `twibooru.org` | Own API (Twitter-based) | Current API state and access rules; may need its own adapter. | Candidate |
| **Hypnohub** | `hypnohub.net` | Danbooru | Posts + tags endpoints; anonymous access. | Candidate |
| **Dollbooru** | `dollbooru.org` | Legacy Danbooru XML | Legacy XML API; may need the older XML adapter path. | Candidate |
| **Paheal** | `rule34.paheal.net` | Own API (DAPI-like but not guaranteed) | Do not assume DAPI compatibility; verify endpoints explicitly. | Candidate |
| **3Dbooru** | `3dbooru.com` | Danbooru | Availability, endpoint stability. | Candidate |
| **Anime-Pictures** | `anime-pictures.net` | Unknown | API or scraping; do not assume standard Booru. | Candidate |
| **Sankaku Complex** | `sankakucomplex.com` | Own API, auth-gated | Authentication model and access limits; likely requires credentials — defer unless anonymous search works. | Candidate |
| **Booru.org** | `booru.org` | Instance factory | Creates user subdomain instances; only add specific active, compatible instances after per-instance verification — never bulk-register subdomains. | Investigate |

**Deferred (documented decision, v1.1.1):**

- **E-Shuushuu** (`e-shuushuu.net`): search endpoint responds anonymously, but the posts endpoint could not be verified without an API key. Deferred per the no-broken-sources policy; revisit if anonymous post access is confirmed.
- **Furbooru**: integrated in v1.1.1 (Philomena family) — no longer a candidate.

**Strategy**

1. Reuse existing adapters first (Danbooru v2, Moebooru, DAPI, Philomena) and only write a new adapter when the API family does not match.
2. Register each new source with the full capability metadata (`api_family`, `auth_required`, `supports_tags`, `supports_rating_filter`, `status`) so the catalog stays honest.
3. Verify live (HTTP status + JSON shape + a real tagged search) before registering, then add a registry test pinning the source.
4. Add new sources in batches of 2–4 per release so the dynamic header badge and README source table stay truthful.

---

## Accepted limitations (documented, not bugs)

- **R7-F (v1.1.1)**: DNS-rebinding window between the SSRF guard's lookup and httpx connect. IP-pinned connections judged disproportionate for this app's threat model; see `assert_public_host`.
- **Rule34.us scraper rating** (R6-21): intentionally conservative — documented in `RELEASES.md`.
- **DAPI unindexed tags** (v1.1.0): new, unindexed DAPI tags with ambiguous parenthesized qualifiers fall back to `character`/`general` by design.

---

## Conventions

- Roadmap items move to `RELEASES.md` once shipped, with the full implementation notes.
- The header source badge is dynamic (counts the registry), so adding sources here requires no UI change — only the README source table needs updating.
