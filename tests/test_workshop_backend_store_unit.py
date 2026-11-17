"""Content-store dedup, link-count reclamation, and no-link fallback."""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

import pytest

from core.workshop.backend import store as store_module
from core.workshop.backend.store import ContentStore, remove_tree

BLOB = os.urandom(200 * 1024)
BLOB_SHA = hashlib.sha256(BLOB).hexdigest()


def write_download(store: ContentStore) -> Path:
    temporary = store.temporary_dir / "model-download"
    temporary.write_bytes(BLOB)
    return temporary


def make_tree(root: Path, extra: bytes) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "shared.bin").write_bytes(BLOB)
    (root / "pkg" / "unique.bin").write_bytes(extra)
    (root / "pkg" / "small.py").write_text("x = 1\n", encoding="utf-8")
    return root


def test_identical_large_files_become_one_physical_object(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "store")
    first = store.adopt_tree(make_tree(tmp_path / "a", os.urandom(100 * 1024)))
    second = store.adopt_tree(make_tree(tmp_path / "b", os.urandom(100 * 1024)))
    assert second.shared_bytes == len(BLOB)
    assert second.new_bytes < first.new_bytes
    a = (tmp_path / "a" / "pkg" / "shared.bin").stat()
    b = (tmp_path / "b" / "pkg" / "shared.bin").stat()
    assert (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)
    assert a.st_nlink == 3  # store + two trees


def test_garbage_collection_follows_link_counts(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "store")
    store.adopt_tree(make_tree(tmp_path / "a", os.urandom(100 * 1024)))
    store.adopt_tree(make_tree(tmp_path / "b", os.urandom(100 * 1024)))
    assert store.usage()[0] == 3
    remove_tree(tmp_path / "a")
    freed = store.collect_garbage()
    # A's unique object is gone; the shared one survives for B.
    assert freed.freed_bytes == 100 * 1024
    assert store.usage()[0] == 2
    assert (tmp_path / "b" / "pkg" / "shared.bin").read_bytes() == BLOB
    remove_tree(tmp_path / "b")
    store.collect_garbage()
    assert store.usage() == (0, 0)


def test_volumes_without_hard_links_fall_back_to_copies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_links(_source, _target):  # noqa: ANN001, ANN202
        raise OSError(1, "hard links are not supported")

    monkeypatch.setattr(store_module.os, "link", no_links)
    store = ContentStore(tmp_path / "store")
    stats = store.adopt_tree(make_tree(tmp_path / "a", os.urandom(1024)))
    assert stats.copied_without_links is True
    # Real physical use is reported instead of pretending to share.
    assert stats.shared_bytes == 0
    assert stats.new_bytes >= len(BLOB)
    assert (tmp_path / "a" / "pkg" / "shared.bin").read_bytes() == BLOB


def test_copied_views_keep_their_object_through_references_and_pins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(_source, _target):  # noqa: ANN001, ANN202
        raise OSError(1, "hard links are not supported")

    store = ContentStore(tmp_path / "store")
    monkeypatch.setattr(store_module.os, "link", no_links)
    view = tmp_path / "views" / "model.bin"
    assert store.import_verified_file(write_download(store), BLOB_SHA, view) is False
    assert view.read_bytes() == BLOB and view.stat().st_nlink == 1
    # Nothing links to the object, but a caller still references it.
    store.collect_garbage(keep={BLOB_SHA})
    assert store.has(BLOB_SHA)
    store.pin([BLOB_SHA])
    store.collect_garbage()
    assert store.has(BLOB_SHA)
    store.unpin([BLOB_SHA])
    assert store.link_existing(BLOB_SHA, tmp_path / "views" / "second.bin") is False
    freed = store.collect_garbage()
    assert freed.freed_bytes == len(BLOB)
    assert not store.has(BLOB_SHA)
    assert store.link_existing(BLOB_SHA, tmp_path / "views" / "third.bin") is None


def test_collection_waits_for_a_link_in_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ContentStore(tmp_path / "store")
    view = tmp_path / "views" / "model.bin"
    real_link = os.link
    collector: list[threading.Thread] = []

    def link_while_collecting(source, target):  # noqa: ANN001, ANN202
        # The published object has no other name yet; collection starting
        # now must not delete it before this link exists.
        thread = threading.Thread(target=store.collect_garbage)
        thread.start()
        thread.join(timeout=0.3)
        collector.append(thread)
        return real_link(source, target)

    monkeypatch.setattr(store_module.os, "link", link_while_collecting)
    assert store.import_verified_file(write_download(store), BLOB_SHA, view) is True
    monkeypatch.setattr(store_module.os, "link", real_link)
    collector[0].join(timeout=10)
    assert not collector[0].is_alive()
    assert store.has(BLOB_SHA)
    assert view.stat().st_nlink == 2


def test_object_collection_leaves_temporary_downloads_to_maintenance(tmp_path: Path) -> None:
    store = ContentStore(tmp_path / "store")
    download = write_download(store)
    store.collect_garbage()
    # A download in progress survives ordinary collection.
    assert download.is_file()
    assert store.clear_temporary().freed_bytes == len(BLOB)
    assert not download.exists()
