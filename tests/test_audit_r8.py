"""
Regression tests for the R8 audit fixes (R8-A, R8-B).

Run with:  python -m pytest tests/test_audit_r8.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import hades_booru.http_client as hc
from hades_booru.http_client import HttpClient
from hades_booru.tag_dictionary.importer import TagDictionaryImporter
from hades_booru.tag_dictionary.service import TagDictionaryService
from tests.http_mocks import DummyClient, make_streamable_response


def _client_with(responses: list[httpx.Response], monkeypatch: pytest.MonkeyPatch) -> DummyClient:
    """Monkeypatches httpx in the http_client module; returns the recording DummyClient."""
    recorder = DummyClient(responses)
    monkeypatch.setattr(
        hc,
        "httpx",
        SimpleNamespace(
            Client=lambda **kw: recorder,
            Timeout=lambda *a, **kw: object(),
            URL=httpx.URL,
            TimeoutException=httpx.TimeoutException,
        ),
    )
    return recorder


# ------------------------------------------------------------------ R8-A: credentials


def test_cross_origin_redirect_drops_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """R8-A core: a 302 to a DIFFERENT origin must go unauthenticated.

    A compromised board (or an open redirect on a legitimate one) must not
    receive the user's API key just because it sits behind a redirect.
    """
    hop = make_streamable_response(
        302,
        httpx.Request("GET", "https://public.example/api"),
        headers={"location": "https://other.example/api"},
    )
    final = make_streamable_response(200, httpx.Request("GET", "https://other.example/api"), text="OK")
    recorder = _client_with([hop, final], monkeypatch)

    assert HttpClient().get_text("https://public.example/api", retries=0, auth=("user", "SECRETKEY")) == "OK"

    assert len(recorder.calls) == 2
    assert recorder.calls[0][2]["auth"] == ("user", "SECRETKEY"), "original origin keeps credentials"
    assert recorder.calls[1][2]["auth"] is None, "cross-origin redirect must NOT receive credentials"


def test_same_origin_redirect_keeps_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """R8-A allowed case: a same-origin 302 (e.g. path upgrade) may keep credentials."""
    hop = make_streamable_response(
        302,
        httpx.Request("GET", "https://board.example/api"),
        headers={"location": "https://board.example/api/v2"},
    )
    final = make_streamable_response(200, httpx.Request("GET", "https://board.example/api/v2"), text="OK")
    recorder = _client_with([hop, final], monkeypatch)

    assert HttpClient().get_text("https://board.example/api", retries=0, auth=("user", "SECRETKEY")) == "OK"

    assert recorder.calls[0][2]["auth"] == ("user", "SECRETKEY")
    assert recorder.calls[1][2]["auth"] == ("user", "SECRETKEY"), "same-origin hop keeps credentials"


# ------------------------------------------------------------------ R8-B: importer resume


def test_importer_resume_recovers_interrupted_enrichment(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8-B core: a mid-import crash must not strand un-enriched tags forever.

    Run 1 of 55 tags dies hard (os._exit) right after 52 wiki fetches — the
    idx=50 checkpoint has fired. The checkpoint must have stored ONLY the
    enriched tags, so run 2 re-enriches the 5-tag tail instead of skipping it.
    (Old code upserted ALL 55 at the checkpoint; resume then did 0 wiki calls
    and 3 tags were silently lost.)
    """
    db = tmp_path / "r8b.sqlite3"
    total = 55
    tag_names = [f"t_{i:02d}" for i in range(1, total + 1)]

    # --- Run 1 in a child process so a hard death (os._exit) is observable.
    child_script = f"""
import os
from pathlib import Path
from hades_booru.tag_dictionary.importer import TagDictionaryImporter
from hades_booru.tag_dictionary.service import TagDictionaryService

svc = TagDictionaryService(db_path=Path({str(db)!r}), auto_seed=False)
im = TagDictionaryImporter(service=svc, base_url=\"https://danbooru.donmai.us\")
TAGS = {tag_names!r}
_wiki_calls = [0]

def fake(url, params=None, auth=None):
    if url.endswith(\"/tags.json\"):
        return [{{\"name\": n, \"category\": 4, \"post_count\": 99}} for n in TAGS]
    if url.endswith(\"/wiki_pages.json\"):
        title = params[\"search[title]\"]
        _wiki_calls[0] += 1
        if _wiki_calls[0] == 53:
            # Hard death: the checkpoint at idx=50 already fired; t_01..t_52 are
            # enriched in memory, t_53 never returned.
            os._exit(97)
        return [{{\"title\": title, \"body\": f\"Definition {{title}}.\"}}]
    if url.endswith(\"/tag_aliases.json\"):
        return []
    return []

import hades_booru.http_client as _hc
_hc.http_client.get_json = fake
im.import_from_danbooru(top={total}, resume=True, throttle=0)
os._exit(0)
"""
    script = tmp_path / "r8b_run1.py"
    script.write_text(child_script, encoding="utf-8")
    # The child must import `hades_booru` from the repo root, regardless of the
    # CWD pytest happens to run from; pin both cwd and PYTHONPATH to the repo.
    repo_root = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONPATH": str(repo_root)}
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        cwd=str(repo_root),
        env=env,
    )
    assert proc.returncode != 0, f"run 1 must die hard before finishing (rc={proc.returncode}, err={proc.stderr.decode(errors='replace')[-500:]})"

    # After the crash: checkpoint invariant — stored tags are enriched, the
    # un-enriched tail (t_51..t_55) was NOT persisted.
    svc = TagDictionaryService(db_path=db, auto_seed=False)
    assert (svc.lookup("t_01") is not None) and svc.lookup("t_01").body_en, "checkpointed tag is stored"
    assert svc.lookup("t_51") is None, "post-checkpoint enrichments are NOT stored yet"
    assert svc.lookup("t_53") is None, "un-enriched tail must NOT be persisted by the checkpoint"
    assert svc.lookup("t_55") is None, "un-enriched tail must NOT be persisted by the checkpoint"

    # --- Run 2: completes; every tag ends up enriched (tail re-fetched, not skipped).
    def fake2(url: str, params: dict | None = None, auth: object = None):
        if url.endswith("/tags.json"):
            return [{"name": n, "category": 4, "post_count": 99} for n in tag_names]
        if url.endswith("/wiki_pages.json"):
            title = params["search[title]"]
            return [{"title": title, "body": f"Definition {title}."}]
        return []

    monkeypatch.setattr("hades_booru.tag_dictionary.importer.http_client.get_json", fake2)
    importer2 = TagDictionaryImporter(service=svc, base_url="https://danbooru.donmai.us")
    importer2.import_from_danbooru(top=total, resume=True, throttle=0)

    for name in tag_names:
        rec = svc.lookup(name)
        assert rec is not None and rec.body_en, f"{name} must be enriched after resume"
