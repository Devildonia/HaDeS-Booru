"""Regression tests for HaDeS-Booru v1.1.2 technical audit findings (HB-01 .. HB-16)."""

from __future__ import annotations

import concurrent.futures
import io
import json
import zipfile
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app import is_loopback_host
from hades_booru.adapters.registry import registry
from hades_booru.config import ConfigManager
from hades_booru.exporter import BulkExporter, validate_media_payload
from hades_booru.image_cache import DiskImageCache
from hades_booru.metadata_extractor import extract_image_metadata
from hades_booru.models import CategorizedTags, Post
from hades_booru.normalizer import PromptNormalizer
from hades_booru.tag_dictionary.importer import TagDictionaryImporter
from hades_booru.tag_dictionary.service import TagDictionaryService
from hades_booru.ui import handlers as handlers_module
from hades_booru.ui.desktop import open_folder_in_explorer, open_native_folder_dialog
from hades_booru.ui.layout import create_gradio_app
from hades_booru.ui.state import PersonalListStore, SessionLists, add_top_tag_to_query


def _make_valid_png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buf, format="PNG")
    return buf.getvalue()


def test_hb01_remote_mode_excludes_desktop_events_and_guards_callbacks(tmp_path: Path) -> None:
    assert is_loopback_host("127.0.0.1") is True
    assert is_loopback_host("localhost") is True
    assert is_loopback_host("::1") is True
    assert is_loopback_host("0.0.0.0") is False
    assert is_loopback_host("192.168.1.50") is False

    remote_app = create_gradio_app(share_mode=True)
    fn_names = {getattr(entry.fn, "__name__", "") for entry in remote_app.fns.values()}
    assert "open_native_folder_dialog" not in fn_names
    assert "open_folder_in_explorer" not in fn_names

    local_app = create_gradio_app(share_mode=False)
    local_fn_names = {getattr(entry.fn, "__name__", "") for entry in local_app.fns.values()}
    assert "open_native_folder_dialog" in local_fn_names
    assert "open_folder_in_explorer" in local_fn_names

    target = tmp_path / "should_not_exist"
    assert open_native_folder_dialog("C:/fallback", "en", share_mode=True) == "C:/fallback"
    msg = open_folder_in_explorer(str(target), "en", share_mode=True)
    assert "share" in msg.lower()
    assert not target.exists()


def test_hb02_credential_deletion_and_rotation_respected_across_instances(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.local.json"
    inst1 = ConfigManager(config_path=cfg_file)
    inst1.set_credentials_many({"danbooru": ("user1", "key1")}, persist_to_disk=True)

    inst2 = ConfigManager(config_path=cfg_file)
    assert inst2.get_credentials("danbooru").api_key == "key1"

    # Instance 1 deletes credentials; Instance 2 saves an unrelated setting.
    assert inst1.clear_credentials()
    inst2.config.language = "es"
    assert inst2.save()

    disk_after_delete = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk_after_delete["credentials"]["danbooru"]["api_key"] == ""

    # Instance 1 rotates key; Instance 2 (untouched) saves again -> disk keeps rotated key.
    inst1.set_credentials_many({"danbooru": ("user1", "key2")}, persist_to_disk=True)
    inst2.config.image_quality = "medium"
    assert inst2.save()

    disk_after_rotate = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk_after_rotate["credentials"]["danbooru"]["api_key"] == "key2"


def test_hb03_exporter_rejects_html_truncated_and_missing_urls(
    tmp_path: Path, monkeypatch
) -> None:
    html_bytes = b"<html><body>Maintenance</body></html>"
    png_bytes = _make_valid_png_bytes()
    mp4_bytes = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isom"

    assert validate_media_payload(png_bytes, "https://x/1.jpg", "image/png") == ".png"
    assert validate_media_payload(mp4_bytes, "https://x/2.mp4", "video/mp4") == ".mp4"

    posts = [
        Post(
            id="1",
            source_id="demo",
            source_name="Demo",
            source_url="https://x/1",
            file_url="https://cdn.example/demo_1.jpg",
            tags=CategorizedTags(general=["1girl"]),
        ),
        Post(
            id="2",
            source_id="demo",
            source_name="Demo",
            source_url="https://x/2",
            file_url="https://cdn.example/demo_2.png",
            tags=CategorizedTags(general=["solo"]),
        ),
        Post(
            id="3",
            source_id="demo",
            source_name="Demo",
            source_url="https://x/3",
            file_url="",
            tags=CategorizedTags(general=["sky"]),
        ),
    ]

    def fake_download(url: str):
        if url.endswith("demo_1.jpg"):
            return html_bytes, "text/html"
        return png_bytes, "image/png"

    monkeypatch.setattr("hades_booru.exporter.http_client.download_bytes", fake_download)

    exporter = BulkExporter()
    zip_path, zip_errors = exporter.create_export_file_with_report(
        posts=posts,
        mode="trainer-zip",
        normalizer=PromptNormalizer(),
        output_dir=tmp_path / "zips",
        include_images_in_zip=True,
    )
    assert len(zip_errors) == 2
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "demo_1.jpg" not in names
        assert "demo_2.png" in names
        assert "errors.txt" in names

    folder = tmp_path / "dataset_dir"
    summary = exporter.export_dataset_to_local_folder(
        posts=posts,
        target_folder=folder,
        normalizer=PromptNormalizer(),
        download_images=True,
    )
    assert summary["saved_img"] == 1
    assert summary["saved_txt"] == 1
    assert summary["failed_img"] == 2
    assert not (folder / "demo_1.jpg").exists()
    assert not (folder / "demo_1.txt").exists()
    assert not (folder / "demo_3.txt").exists()
    assert (folder / "demo_2.png").exists()


def test_hb04_share_mode_isolates_search_history(tmp_path: Path, monkeypatch) -> None:
    cfg_file = tmp_path / "config.local.json"
    cm = ConfigManager(config_path=cfg_file)
    cm.config.search_history = ["secret_host_tag"]
    cm.save()
    monkeypatch.setattr(handlers_module, "config_manager", cm)
    monkeypatch.setattr("hades_booru.ui.layout.config_manager", cm)

    app = create_gradio_app(share_mode=True)
    app_cfg = app.get_config_file()
    comps = {c["id"]: c for c in app_cfg.get("components", [])}
    dropdown_choices = [
        c.get("props", {}).get("choices", [])
        for c in comps.values()
        if c.get("type") == "dropdown"
    ]
    flat = [item for sub in dropdown_choices for item in (sub or [])]
    assert "secret_host_tag" not in str(flat)

    def failing_dispatch(*args, **kwargs):
        raise RuntimeError("boom")

    store = PersonalListStore(share_mode=True)
    handlers = handlers_module.create_ui_handlers(store, failing_dispatch)
    sess = SessionLists()
    res = handlers["execute_search_handler"](
        "danbooru",
        "visitor_tag",
        20,
        "all",
        "text",
        "en",
        False,
        False,
        False,
        "",
        "general",
        ", ",
        "dataset",
        "",
        "",
        [],
        False,
        sess,
    )
    # Error path must not leak host search_history in recent/top_tags dropdown updates.
    assert "secret_host_tag" not in str(res[-2])
    assert "secret_host_tag" not in str(res[-1])


def test_hb05_second_save_does_not_revert_other_instance_changes(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.local.json"
    inst_a = ConfigManager(config_path=cfg_file)
    inst_b = ConfigManager(config_path=cfg_file)

    inst_a.config.language = "es"
    assert inst_a.save()

    inst_b.config.image_quality = "medium"
    assert inst_b.save()
    assert inst_b.save()

    disk = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert disk["language"] == "es"
    assert disk["image_quality"] == "medium"


def test_hb06_parallel_exports_never_overwrite_each_other(tmp_path: Path) -> None:
    exporter = BulkExporter()
    norm = PromptNormalizer()
    posts = [
        Post(
            id="10",
            source_id="danbooru",
            source_name="Danbooru",
            source_url="https://danbooru.donmai.us/posts/10",
            tags=CategorizedTags(general=["1girl"]),
        )
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(
            exporter.create_export_file_with_report,
            posts,
            "dataset",
            norm,
            tmp_path,
            "Danbooru",
            "1girl",
        )
        f2 = pool.submit(
            exporter.create_export_file_with_report,
            posts,
            "dataset",
            norm,
            tmp_path,
            "Danbooru",
            "1girl",
        )
        p1, _ = f1.result()
        p2, _ = f2.result()

    assert p1 != p2
    assert p1.exists() and p2.exists()


def test_hb07_and_hb08_importer_resumes_incomplete_and_tolerates_bad_records(
    tmp_path: Path, monkeypatch
) -> None:
    svc = TagDictionaryService(db_path=tmp_path / "tags.sqlite3", auto_seed=False)
    importer = TagDictionaryImporter(service=svc)

    def fake_fetch_json(url: str, params: dict, auth):
        if url.endswith("/tags.json"):
            return [
                {"name": "alpha_tag", "category": "bad_cat", "post_count": "not_a_num"},
            ]
        if url.endswith("/wiki_pages.json"):
            return [{"body": "Alpha definition"}]
        if url.endswith("/tag_aliases.json"):
            return []
        return []

    monkeypatch.setattr(importer, "_fetch_json", fake_fetch_json)

    # First run with skip_wiki=True; bad category/post_count must not abort.
    assert importer.import_from_danbooru(top=1, skip_wiki=True, resume=True, throttle=0) == 1
    rec1 = svc.lookup("alpha_tag")
    assert rec1 is not None
    assert rec1.body_en == ""

    # Second run with skip_wiki=False, resume=True -> completes missing wiki body.
    assert importer.import_from_danbooru(top=1, skip_wiki=False, resume=True, throttle=0) == 1
    rec2 = svc.lookup("alpha_tag")
    assert rec2 is not None
    assert rec2.body_en == "Alpha definition"


def test_hb09_prune_counts_only_actual_deletions(tmp_path: Path, monkeypatch) -> None:
    cache = DiskImageCache(cache_dir=tmp_path / "cache", max_files=1)
    f1 = cache._dir / "a.png"
    f2 = cache._dir / "b.png"
    f1.write_bytes(b"123")
    f2.write_bytes(b"456")

    orig_unlink = Path.unlink

    def flaky_unlink(self: Path, missing_ok: bool = False) -> None:
        if self.name == "a.png":
            raise OSError("locked")
        orig_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    cache.prune_if_needed()
    # Even though a.png failed to unlink, b.png was still attempted and deleted.
    assert f1.exists()
    assert not f2.exists()


def test_hb10_and_hb11_direct_urls_and_query_encoding() -> None:
    da = registry.detect_source_from_url("https://www.deviantart.com/artist/art/Demo-Work-12345")
    assert da is not None and da.is_direct_post is True

    derpi = registry.detect_source_from_url("https://derpibooru.org/123456")
    assert derpi is not None and derpi.is_direct_post is True

    plus = registry.detect_source_from_url("https://danbooru.donmai.us/posts?tags=c%2B%2B+1girl")
    assert plus is not None and plus.extracted_tags == "c++ 1girl"

    updated, _ = add_top_tag_to_query("https://derpibooru.org/search?q=pony", "cute")
    assert "q=pony+cute" in updated or "q=pony%20cute" in updated
    assert "tags=" not in updated


def test_hb12_and_hb15_comfyui_intermediate_nodes_and_settings_only_png(tmp_path: Path) -> None:
    graph = {
        "1": {"inputs": {"text": "1girl, solo"}},
        "2": {"inputs": {"text": "lowres"}},
        "3": {"inputs": {"conditioning": ["1", 0]}},
        "4": {"inputs": {"positive": ["3", 0], "negative": ["2", 0]}},
    }
    png_comfy = tmp_path / "comfy.png"
    info = PngInfo()
    info.add_text("prompt", json.dumps(graph))
    Image.new("RGB", (8, 8), "white").save(png_comfy, pnginfo=info)

    meta_comfy = extract_image_metadata(png_comfy)
    assert meta_comfy.found is True
    assert meta_comfy.prompt == "1girl, solo"
    assert meta_comfy.negative == "lowres"

    png_settings = tmp_path / "settings_only.png"
    info2 = PngInfo()
    info2.add_text("parameters", "Steps: 20, Sampler: Euler")
    Image.new("RGB", (8, 8), "white").save(png_settings, pnginfo=info2)

    meta_settings = extract_image_metadata(png_settings)
    assert meta_settings.found is True
    assert meta_settings.settings == "Steps: 20, Sampler: Euler"


def test_hb14_and_hb16_packaging_and_start_sh() -> None:
    root = Path(__file__).resolve().parent.parent
    start_sh = (root / "start.sh").read_text(encoding="utf-8")
    assert "dirname" in start_sh and "cd " in start_sh

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "[build-system]" in pyproject
    assert 'include = ["hades_booru*"]' in pyproject
