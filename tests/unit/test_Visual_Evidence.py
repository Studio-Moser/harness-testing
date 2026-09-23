import base64
import copy
import hashlib
import json
import runpy
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness_testing.Visual_Evidence import grading_inputs, visual_evidence


def test_frozen_visual_contrast_helpers_cover_alpha_and_ancestor_opacity():
    root = Path(__file__).resolve().parents[2]
    helpers = [
        root / "tasks/workflow" / task / "environment/Visual_Contrast.js"
        for task in (
            "static-notification-card-polish",
            "static-workspace-design-system-polish",
            "static-responsive-settings-polish",
        )
    ]
    assert len({path.read_bytes() for path in helpers}) == 1
    subprocess.run(
        ["node", str(root / "tests/Support/Visual_Contrast_Check.js"), str(helpers[0])],
        check=True,
        capture_output=True,
    )


def png(width):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00" + b"\xff" * width * 3))
        + chunk(b"IEND", b"")
    )


def grading_packet():
    images = [
        {
            "viewport_width": width,
            "view": "settings",
            "media_type": "image/png",
            "digest": "sha256:" + hashlib.sha256(png(width)).hexdigest(),
            "base64": base64.b64encode(png(width)).decode(),
        }
        for width in (320, 768, 1440)
    ]
    return {
        "work_evidence": {
            "base_files": {
                "app.js": {"content_base64": base64.b64encode(b"const value = 1;").decode()},
                "binary": {"content_base64": base64.b64encode(b"\xff\xfe").decode()},
            },
            "visual_evidence": {"status": "complete", "images": images},
        }
    }


def test_grading_inputs_present_source_and_images_without_mutating_frozen_packet():
    packet = grading_packet()
    original = copy.deepcopy(packet)
    inputs = grading_inputs(packet)
    text = json.loads(inputs[0]["text"])["work_evidence"]
    assert text["base_files"]["app.js"] == {"content": "const value = 1;"}
    assert text["base_files"]["binary"] == original["work_evidence"]["base_files"]["binary"]
    assert len(inputs) == 4
    pairs = zip(text["visual_evidence"]["images"], inputs[1:], strict=True)
    for number, (item, image) in enumerate(pairs, 1):
        assert "base64" not in item
        assert item["input_image_number"] == number
        assert image["type"] == "image"
        encoded = original["work_evidence"]["visual_evidence"]["images"][number - 1]["base64"]
        assert image["url"] == "data:image/png;base64," + encoded
    assert packet == original
    assert grading_inputs({"task": "text only"}) == [
        {
            "type": "text",
            "text": '{"task": "text only"}',
            "text_elements": [],
        }
    ]
    review = {"visual_evidence": original["work_evidence"]["visual_evidence"]}
    assert len(grading_inputs(review)) == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("base64", "https://example.com/image.png"),
        ("base64", "/tmp/image.png"),
        ("base64", "A" * 2_666_669),
        ("media_type", "image/jpeg"),
        ("digest", "sha256:" + "0" * 64),
        ("viewport_width", 321),
    ],
)
def test_grading_inputs_reject_invalid_or_changed_images(field, value):
    packet = grading_packet()
    packet["work_evidence"]["visual_evidence"]["images"][0][field] = value
    with pytest.raises(ValueError):
        grading_inputs(packet)


@pytest.mark.parametrize("count", [0, 13])
def test_grading_inputs_require_bounded_complete_images(count):
    packet = grading_packet()
    images = packet["work_evidence"]["visual_evidence"]["images"]
    packet["work_evidence"]["visual_evidence"]["images"] = [images[0]] * count
    with pytest.raises(ValueError, match="count"):
        grading_inputs(packet)


def test_visual_evidence_is_frozen_without_host_paths_and_missing_images_stay_unknown(tmp_path):
    task = tmp_path / "task"
    trial = tmp_path / "trial"
    assert visual_evidence(task, trial) is None
    (task / "environment").mkdir(parents=True)
    (task / "environment/Visual Review.md").write_text("Inspect hierarchy and responsive layouts.")
    assert visual_evidence(task, trial)["status"] == "unavailable"
    directory = trial / "verifier/visual"
    directory.mkdir(parents=True)
    for width in (320, 768, 1440):
        (directory / f"settings-{width}.png").write_bytes(png(width))
    result = visual_evidence(task, trial)
    assert result["status"] == "complete"
    assert len(result["images"]) == 3
    assert str(tmp_path) not in str(result)
    original = base64.b64decode(result["images"][0]["base64"])
    (directory / "settings-320.png").write_bytes(b"invalid")
    assert visual_evidence(task, trial)["status"] == "unavailable"
    assert base64.b64decode(result["images"][0]["base64"]) == original
    for invalid in (
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + struct.pack(">II", 320, 1000),
        original[:-1],
        png(321),
        original[:-5] + b"\x00" * 5,
    ):
        (directory / "settings-320.png").write_bytes(invalid)
        assert visual_evidence(task, trial)["status"] == "unavailable"


def test_bad_layout_still_captures_every_viewport(tmp_path, monkeypatch):
    captured = []

    class Page:
        def __init__(self, width):
            self.width = width

        def route(self, *args):
            pass

        def goto(self, *args):
            pass

        def screenshot(self, **kwargs):
            captured.append(self.width)

        def close(self):
            pass

        def evaluate(self, *args):
            return {"overflow": True}

    class Browser:
        def new_page(self, *, viewport, **kwargs):
            return Page(viewport["width"])

        def close(self):
            pass

    class Playwright:
        def __enter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=Browser))

        def __exit__(self, *args):
            pass

    monkeypatch.setitem(
        sys.modules, "playwright.sync_api", SimpleNamespace(sync_playwright=Playwright)
    )
    monkeypatch.setenv("VISUAL_OUTPUT_DIRECTORY", str(tmp_path))
    check = Path(__file__).resolve().parents[2] / (
        "tasks/workflow/static-responsive-settings-polish/environment/Visual_Check.py"
    )
    monkeypatch.chdir(check.parent)
    with pytest.raises(AssertionError, match="horizontal overflow"):
        runpy.run_path(str(check))["main"]()
    assert captured == [320, 768, 1440]


def test_multiview_requires_every_frozen_route_and_preserves_labels(tmp_path):
    task, trial = tmp_path / "task", tmp_path / "trial"
    (task / "environment").mkdir(parents=True)
    (task / "environment/Visual Review.md").write_text("Compare all routes.")
    manifest = task / "environment/Visual Views.json"
    views = ["overview", "projects", "settings", "activity"]
    manifest.write_text(json.dumps(views))
    directory = trial / "verifier/visual"
    directory.mkdir(parents=True)
    for view in views:
        for width in (320, 768, 1440):
            (directory / f"{view}-{width}.png").write_bytes(png(width))
    result = visual_evidence(task, trial)
    assert result["status"] == "complete"
    assert [(i["view"], i["viewport_width"]) for i in result["images"]] == [
        (view, width) for view in views for width in (320, 768, 1440)
    ]
    (directory / "activity-1440.png").unlink()
    assert visual_evidence(task, trial)["reason"] == "missing_verifier_screenshot"
    for invalid in ([], ["../private"], ["same", "same"], [1], {}, views + ["extra"]):
        manifest.write_text(json.dumps(invalid))
        assert visual_evidence(task, trial)["reason"] == "invalid_visual_views"
    manifest.write_text("invalid json")
    assert visual_evidence(task, trial)["reason"] == "invalid_visual_views"
    manifest.unlink()
    manifest.symlink_to(task / "missing-manifest")
    assert visual_evidence(task, trial)["reason"] == "invalid_visual_views"
