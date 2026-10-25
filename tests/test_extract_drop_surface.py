"""Regression: drop-to-replace surface on the Image-to-Prompt tab (Gradio 6.30).

Gradio 6.30's File component shrinks the native drop zone to a 16px corner icon
once a file is loaded; the visible file row then rejects drops, so "load a new
image on top of the loaded one" silently breaks. The app compensates with a
page-level JS hook (`hades_booru/ui/layout._EXTRACT_DROP_SURFACE_JS`) that
retargets file drops on the whole component block back to the upload button.
The hook is anchored to the extract input's `elem_id` and is passed through
`launch(js=...)` in `app.py` (Gradio 6 moved the page `js` hook from the
Blocks constructor to launch). Losing any of these three links re-breaks the
feature with no visible error, so all three are pinned here.

Verified in a real headless browser (Chrome CDP): drops onto the upload
button, onto the loaded file row, and in mixed sequences all upload and
re-run extraction with the newest file winning.
"""

from __future__ import annotations

import pathlib

import pytest

from hades_booru.ui.layout import _EXTRACT_DROP_SURFACE_JS, create_gradio_app


@pytest.fixture(scope="module")
def app():
    return create_gradio_app()


def test_js_hook_contains_anchor_and_mechanics() -> None:
    js = _EXTRACT_DROP_SURFACE_JS
    assert "hades-extract-file" in js, "must anchor to the extract input elem_id"
    assert "button.upload-container" in js, "must retarget onto the Gradio upload button"
    assert "__hadesDropRT" in js, "must guard against re-dispatch loops"
    assert "dragover" in js and "drop" in js
    assert "'Files'" in js, "must only intercept file drags, never text drags"


def test_extract_file_input_has_anchor_elem_id(app) -> None:
    # Gradio 6: app.blocks is a dict (id -> component)
    components = app.blocks.values() if isinstance(app.blocks, dict) else app.blocks
    anchored = [c for c in components if getattr(c, "elem_id", None) == "hades-extract-file"]
    assert len(anchored) == 1, "exactly one component may use the drop-surface anchor"
    assert anchored[0].file_count == "multiple", "newest-file-wins relies on the file list"


def test_app_launch_wires_js_hook() -> None:
    # Gradio 6: page-level js belongs on launch(), not Blocks(). Pin the wiring
    # in app.py so a refactor that drops it cannot ship unnoticed.
    app_py = pathlib.Path(__file__).resolve().parent.parent / "app.py"
    text = app_py.read_text(encoding="utf-8")
    assert "js=_EXTRACT_DROP_SURFACE_JS" in text
    assert "_EXTRACT_DROP_SURFACE_JS" in text.split("from hades_booru.ui.layout import", 1)[1]
