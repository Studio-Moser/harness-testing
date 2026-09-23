"""Freeze verifier-rendered images into private, identity-blind grading packets."""

import base64
import copy
import hashlib
import json
import re
import struct
import zlib
from pathlib import Path


def grading_inputs(packet: dict) -> list[dict]:
    """Present frozen text as text and PNGs as image inputs, without URLs or host paths."""
    presented = copy.deepcopy(packet)
    work = presented.get("work_evidence", {})
    for file in (work.get("base_files") or {}).values():
        contents = base64.b64decode(file["content_base64"], validate=True)
        try:
            text = contents.decode("utf-8")
        except UnicodeDecodeError:
            continue  # Binary files retain their original byte representation.
        file["content"] = text
        del file["content_base64"]
    visuals = work.get("visual_evidence") or presented.get("visual_evidence")
    images = []
    if visuals and visuals["status"] == "complete":
        if not 1 <= len(visuals["images"]) <= 12:
            raise ValueError("invalid grading image count")
        for index, item in enumerate(visuals["images"], start=1):
            encoded = item.pop("base64")
            if len(encoded) > 2_666_668 or item["media_type"] != "image/png":
                raise ValueError("invalid grading image encoding")
            contents = base64.b64decode(encoded, validate=True)
            if (
                len(contents) > 2_000_000
                or not _valid_screenshot(contents, item["viewport_width"])
                or "sha256:" + hashlib.sha256(contents).hexdigest() != item["digest"]
            ):
                raise ValueError("grading image differs from frozen screenshot")
            item["input_image_number"] = index
            images.append({"type": "image", "url": "data:image/png;base64," + encoded})
    return [{"type": "text", "text": json.dumps(presented), "text_elements": []}, *images]


def _valid_screenshot(contents: bytes, width: int) -> bool:
    """Validate the non-interlaced 8-bit RGB/RGBA PNGs emitted by Chromium."""
    if not contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset, header, compressed = 8, None, bytearray()
    while offset + 12 <= len(contents):
        size = struct.unpack(">I", contents[offset : offset + 4])[0]
        end = offset + 12 + size
        if end > len(contents):
            return False
        kind = contents[offset + 4 : offset + 8]
        data = contents[offset + 8 : end - 4]
        if zlib.crc32(kind + data) != struct.unpack(">I", contents[end - 4 : end])[0]:
            return False
        if kind == b"IHDR":
            if offset != 8 or size != 13:
                return False
            w, h, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
            if w != width or h < 1 or depth != 8 or color not in (2, 6):
                return False
            if compression or filtering or interlace:
                return False
            header = (h, 1 + w * (3 if color == 2 else 4))
        elif header is None:
            return False
        elif kind == b"IDAT":
            compressed.extend(data)
        elif kind == b"IEND":
            if size or end != len(contents) or not compressed:
                return False
            height, stride = header
            expected = height * stride
            if expected > 32_000_000:
                return False
            decoder = zlib.decompressobj()
            try:
                pixels = decoder.decompress(compressed, expected + 1)
            except zlib.error:
                return False
            return (
                decoder.eof
                and not decoder.unused_data
                and not decoder.unconsumed_tail
                and len(pixels) == expected
                and all(pixels[row * stride] <= 4 for row in range(height))
            )
        elif not kind[0] & 32:  # Unknown critical chunks are not a supported screenshot.
            return False
        offset = end
    return False


def visual_evidence(task_root: Path, trial_directory: Path) -> dict | None:
    rubric = task_root / "environment/Visual Review.md"
    if not rubric.is_file():
        return None
    views_path = task_root / "environment/Visual Views.json"
    views = ["settings"]
    if views_path.is_symlink():
        return {"status": "unavailable", "reason": "invalid_visual_views"}
    if views_path.exists():
        try:
            views = json.loads(views_path.read_text())
            if (
                not isinstance(views, list)
                or not 1 <= len(views) <= 4
                or any(
                    not isinstance(v, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", v)
                    for v in views
                )
                or len(set(views)) != len(views)
            ):
                return {"status": "unavailable", "reason": "invalid_visual_views"}
        except (OSError, ValueError):
            return {"status": "unavailable", "reason": "invalid_visual_views"}
    images = []
    for view, width in ((view, width) for view in views for width in (320, 768, 1440)):
        path = trial_directory / "verifier/visual" / f"{view}-{width}.png"
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.resolve().is_relative_to(trial_directory.resolve())
        ):
            return {"status": "unavailable", "reason": "missing_verifier_screenshot"}
        if path.stat().st_size > 2_000_000:
            return {"status": "unavailable", "reason": "invalid_verifier_screenshot"}
        contents = path.read_bytes()
        if not _valid_screenshot(contents, width):
            return {"status": "unavailable", "reason": "invalid_verifier_screenshot"}
        images.append(
            {
                "viewport_width": width,
                "view": view,
                "media_type": "image/png",
                "digest": "sha256:" + hashlib.sha256(contents).hexdigest(),
                "base64": base64.b64encode(contents).decode("ascii"),
            }
        )
    return {"status": "complete", "rubric": rubric.read_text(), "images": images}
