from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from api.preview_mesh_cache import RecentPreviewMesh


def test_overlapping_requests_share_one_build_and_each_owns_its_file(tmp_path: Path) -> None:
    recent = RecentPreviewMesh()
    started, finish = Event(), Event()
    first, second = tmp_path / "first.glb", tmp_path / "second.glb"
    state = {"color_contours": {"red": [[[0.0, 1.0]]]}}

    def build() -> str:
        started.set()
        assert finish.wait(5)
        first.write_bytes(b"geometry")
        return str(first)

    try:
        with ThreadPoolExecutor(2) as pool:
            owner = pool.submit(recent.render, b"A", state, str(first), build)
            assert started.wait(5)
            other = {}
            duplicate = pool.submit(recent.render, b"A", other, str(second), lambda: pytest.fail("duplicate build"))
            finish.set()
            assert owner.result(timeout=5) == str(first)
            assert duplicate.result(timeout=5) == str(second)
        first.unlink()
        assert second.read_bytes() == b"geometry"
        assert other["color_contours"] == state["color_contours"]
        assert other["color_contours"] is not state["color_contours"]
    finally:
        recent.clear()


def test_failed_build_can_be_retried(tmp_path: Path) -> None:
    recent = RecentPreviewMesh()
    path = tmp_path / "next.glb"

    def fail() -> None:
        raise RuntimeError("mesh failed")

    try:
        with pytest.raises(RuntimeError, match="mesh failed"):
            recent.render(b"A", {}, str(path), fail)
        assert recent.render(b"A", {}, str(path), lambda: None) is None
        path.write_bytes(b"retry")
        assert recent.render(b"A", {}, str(path), lambda: str(path)) == str(path)
    finally:
        recent.clear()


def test_cache_storage_failure_still_returns_the_session_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    recent = RecentPreviewMesh()
    path = tmp_path / "rendered.glb"

    def no_space():
        raise OSError("Cannot create a temporary file")

    monkeypatch.setattr("api.preview_mesh_cache.tempfile.TemporaryFile", no_space)
    path.write_bytes(b"ready")
    assert recent.render(b"A", {}, str(path), lambda: str(path)) == str(path)
    assert path.read_bytes() == b"ready"
