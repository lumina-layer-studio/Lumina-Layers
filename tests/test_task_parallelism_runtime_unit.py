"""Unit coverage for cross-process task-parallelism runtime state."""

from __future__ import annotations

import json
import multiprocessing
from multiprocessing.connection import Connection
import os
from pathlib import Path
import shutil
import threading
from unittest.mock import patch

import pytest


def _runtime_module():
    from core import task_parallelism_runtime

    return task_parallelism_runtime


def test_snapshot_publish_retries_transient_reader_sharing(monkeypatch, tmp_path: Path) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(max_workers=4, parent_dir=tmp_path)
    real_replace = runtime.os.replace
    attempts = []

    def replace(source, target):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError("snapshot reader still holds file")
        return real_replace(source, target)

    monkeypatch.setattr(runtime.os, "replace", replace)
    try:
        publisher.increment()
        assert len(attempts) == 3
        assert runtime.read_outer_demand(publisher.snapshot_path, fallback_outer_workers=4).outer_demand == 1
    finally:
        publisher.cleanup()


def test_publisher_round_trip_tracks_outstanding_tasks(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=4,
        parent_dir=tmp_path,
    )
    try:
        initial = runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=4,
        )
        assert initial.outer_demand == 1
        assert initial.generation == 0
        assert initial.snapshot_fallback is False

        publisher.increment()
        publisher.increment()
        state = runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=4,
        )
        assert state.outer_demand == 2
        assert state.outer_max_workers == 4
        assert state.generation == 2
        assert state.snapshot_fallback is False

        publisher.decrement()
        assert runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=4,
        ).outer_demand == 1
        assert publisher.outstanding == 1
    finally:
        publisher.cleanup()


def test_demand_recreates_the_runtime_directory_without_resetting_counts(tmp_path: Path) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(max_workers=4, parent_dir=tmp_path)
    snapshot = publisher.snapshot_path
    try:
        publisher.increment()
        shutil.rmtree(snapshot.parent)
        publisher.increment()
        assert json.loads(snapshot.read_text(encoding="utf-8"))["outstanding"] == 2

        shutil.rmtree(snapshot.parent)
        publisher.decrement()
        state = runtime.read_outer_demand(snapshot, fallback_outer_workers=4)
        assert (state.outer_demand, state.generation, state.snapshot_fallback) == (1, 3, False)
        publisher.decrement()
        assert json.loads(snapshot.read_text(encoding="utf-8"))["outstanding"] == 0

        shutil.rmtree(snapshot.parent)
        publisher.cleanup()
        publisher.cleanup()
        assert not snapshot.parent.exists()
    finally:
        publisher.cleanup()


@pytest.mark.parametrize("disappears_at", ["open", "replace"])
def test_demand_publish_recovers_when_the_directory_disappears_mid_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, disappears_at: str,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(max_workers=2, parent_dir=tmp_path)
    snapshot = publisher.snapshot_path
    original_open = Path.open
    original_replace = runtime.os.replace
    attempts = 0

    def prune_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            shutil.rmtree(snapshot.parent)

    def open_temp(path, *args, **kwargs):
        if path.parent == snapshot.parent and path.name.startswith(".demand.json-"):
            prune_once()
        return original_open(path, *args, **kwargs)

    def replace_temp(source, target):
        if target == snapshot:
            prune_once()
        return original_replace(source, target)

    if disappears_at == "open":
        monkeypatch.setattr(Path, "open", open_temp)
    else:
        monkeypatch.setattr(runtime.os, "replace", replace_temp)
    try:
        publisher.increment()
        assert attempts == 2
        assert json.loads(snapshot.read_text(encoding="utf-8"))["outstanding"] == 1
        assert not list(snapshot.parent.glob("*.tmp"))
    finally:
        publisher.cleanup()


def test_queued_demand_is_published_but_clamped_to_outer_capacity(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=2,
        parent_dir=tmp_path,
    )
    try:
        for _index in range(5):
            publisher.increment()

        payload = json.loads(
            publisher.snapshot_path.read_text(encoding="utf-8")
        )
        state = runtime.read_outer_demand(
            publisher.snapshot_path,
            fallback_outer_workers=2,
        )

        assert payload["outstanding"] == 5
        assert state.outer_demand == 2
        assert state.outer_max_workers == 2
        assert state.snapshot_fallback is False
    finally:
        publisher.cleanup()


def test_snapshot_contains_only_bounded_control_fields(tmp_path: Path) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=3,
        parent_dir=tmp_path,
    )
    try:
        payload = json.loads(
            publisher.snapshot_path.read_text(encoding="utf-8")
        )
        assert set(payload) == {
            "version",
            "generation",
            "outstanding",
            "outer_max_workers",
            "updated_monotonic_ns",
        }
        assert all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in payload.values()
        )
    finally:
        publisher.cleanup()


def test_missing_snapshot_uses_configured_fair_share(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()

    state = runtime.read_outer_demand(
        tmp_path / "missing.json",
        fallback_outer_workers=3,
    )

    assert state.outer_demand == 3
    assert state.outer_max_workers == 3
    assert state.generation == 0
    assert state.snapshot_fallback is True


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        "[]",
        '{"version": 99, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": -1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": -1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": 1000001, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 0, "updated_monotonic_ns": 1}',
        '{"version": 1, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": -1}',
        '{"version": true, "generation": 1, "outstanding": 1, '
        '"outer_max_workers": 2, "updated_monotonic_ns": 1}',
    ],
)
def test_invalid_snapshot_fails_closed_to_configured_outer_workers(
    tmp_path: Path,
    payload: str,
) -> None:
    runtime = _runtime_module()
    snapshot_path = tmp_path / "demand.json"
    snapshot_path.write_text(payload, encoding="utf-8")

    state = runtime.read_outer_demand(
        snapshot_path,
        fallback_outer_workers=4,
    )

    assert state.outer_demand == 4
    assert state.outer_max_workers == 4
    assert state.snapshot_fallback is True


def test_concurrent_atomic_updates_never_raise_or_return_invalid_demand(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(
        max_workers=4,
        parent_dir=tmp_path,
    )
    start = threading.Event()
    failures: list[BaseException] = []

    def update_repeatedly() -> None:
        try:
            start.wait(timeout=1)
            for _index in range(100):
                publisher.increment()
                publisher.decrement()
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    thread = threading.Thread(target=update_repeatedly)
    thread.start()
    start.set()
    try:
        for _index in range(200):
            state = runtime.read_outer_demand(
                publisher.snapshot_path,
                fallback_outer_workers=4,
            )
            assert 1 <= state.outer_demand <= 4
            assert 1 <= state.outer_max_workers <= 4
    finally:
        thread.join(timeout=2)
        publisher.cleanup()

    assert not thread.is_alive()
    assert failures == []


def test_publishers_use_unique_paths_and_cleanup_is_idempotent(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    first = runtime.OuterDemandPublisher(
        max_workers=2,
        parent_dir=tmp_path,
    )
    second = runtime.OuterDemandPublisher(
        max_workers=2,
        parent_dir=tmp_path,
    )
    first_path = first.snapshot_path
    second_path = second.snapshot_path

    assert first_path != second_path
    assert first_path.is_file()
    assert second_path.is_file()

    first.cleanup()
    first.cleanup()
    second.cleanup()

    assert not first_path.exists()
    assert not second_path.exists()
    assert not first_path.parent.exists()
    assert not second_path.parent.exists()


def test_runtime_scope_restores_the_previous_path(tmp_path: Path) -> None:
    runtime = _runtime_module()
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    assert runtime.current_demand_snapshot_path() is None
    with runtime.task_parallelism_runtime_scope(first):
        assert runtime.current_demand_snapshot_path() == first
        with runtime.task_parallelism_runtime_scope(second):
            assert runtime.current_demand_snapshot_path() == second
        assert runtime.current_demand_snapshot_path() == first
    assert runtime.current_demand_snapshot_path() is None


def test_publisher_owns_a_worker_lease_table_beside_the_snapshot(
    tmp_path: Path,
) -> None:
    """Inner stages need one shared place to publish their real worker count."""

    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(max_workers=4, parent_dir=tmp_path)
    lease_path = publisher.worker_lease_path
    try:
        assert lease_path.parent == publisher.snapshot_path.parent
        assert lease_path.name == runtime.WORKER_LEASE_FILENAME
        # The table starts empty: no inner stage has reserved anything yet.
        assert runtime.read_worker_leases(lease_path) == ({}, False)
        store = runtime.WorkerLeaseStore(lease_path)
        grant = store.reserve(
            requested_workers=2, effective_cpu_capacity=8, stage="test"
        )
        leases, invalid = runtime.read_worker_leases(lease_path)
        assert invalid is False
        assert leases[grant.token]["workers"] == 2
        store.release(grant.token)
        assert runtime.read_worker_leases(lease_path)[0] == {}
    finally:
        publisher.cleanup()

    assert not lease_path.exists()
    assert not publisher.snapshot_path.parent.exists()


@pytest.mark.parametrize("remove_during_open", [False, True], ids=["before-lock", "during-lock-open"])
def test_worker_lease_recovers_the_lock_and_table_after_directory_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remove_during_open: bool,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(max_workers=2, parent_dir=tmp_path)
    store = runtime.WorkerLeaseStore(publisher.worker_lease_path)
    lock = runtime.worker_lease_lock_path(store.path)
    old_grant = store.reserve(requested_workers=2, effective_cpu_capacity=4, stage="fixture")
    opens = 0

    def open_lock(path, mode, **kwargs):
        nonlocal opens
        if path == lock:
            opens += 1
            if opens == 1:
                shutil.rmtree(lock.parent)
        return open(path, mode, **kwargs)

    if remove_during_open:
        monkeypatch.setattr(runtime, "open", open_lock, raising=False)
    else:
        shutil.rmtree(lock.parent)
    try:
        grant = store.reserve(requested_workers=2, effective_cpu_capacity=4, stage="fixture")
        assert (grant.state, grant.workers) == ("granted", 2)
        if remove_during_open:
            assert opens == 2
        assert lock.is_file() and store.path.is_file()
        assert store.release(old_grant.token)
        assert runtime.read_worker_leases(store.path)[0].keys() == {grant.token}
        assert store.release(grant.token)
        assert runtime.read_worker_leases(store.path) == ({}, False)
    finally:
        publisher.cleanup()


@pytest.mark.skipif(os.name == "nt", reason="Windows keeps the open lock file from being deleted")
def test_unlinking_the_posix_lock_file_does_not_split_the_lock(tmp_path: Path) -> None:
    runtime = _runtime_module()
    lock = tmp_path / "workers.lock"

    with runtime._exclusive_file_lock(lock) as first:
        assert first is not None
        lock.unlink()
        with runtime._exclusive_file_lock(lock, timeout_seconds=0) as second:
            assert second is None

    with runtime._exclusive_file_lock(lock, timeout_seconds=0) as second:
        assert second is not None


@pytest.mark.skipif(os.name == "nt", reason="Windows keeps the open lock file from being deleted")
@pytest.mark.parametrize("operation", ["reserve", "release"])
def test_recreated_lease_table_preserves_the_new_lock_holders_reservation(
    tmp_path: Path, operation: str,
) -> None:
    runtime = _runtime_module()
    publisher = runtime.OuterDemandPublisher(max_workers=2, parent_dir=tmp_path)
    table = publisher.worker_lease_path
    context = multiprocessing.get_context("spawn")
    coordinator, worker = context.Pipe()
    process = context.Process(target=_pause_lease_before_replace, args=(table, operation, worker))
    try:
        process.start()
        worker.close()
        assert coordinator.poll(10) and coordinator.recv() == "staged"

        shutil.rmtree(table.parent)
        second = runtime.WorkerLeaseStore(table)
        new_grant = second.reserve(requested_workers=4, effective_cpu_capacity=4, stage="second")
        assert new_grant.workers == 4

        coordinator.send("resume")
        assert coordinator.poll(10)
        recovered = coordinator.recv()
        if operation == "reserve":
            assert recovered.workers == 0
        else:
            assert recovered is True
        leases, invalid = runtime.read_worker_leases(table)
        assert not invalid and leases[new_grant.token]["workers"] == 4
        assert sum(entry["workers"] for entry in leases.values()) == 4

        coordinator.send("stop")
        process.join(10)
        assert process.exitcode == 0
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        coordinator.close()
        worker.close()
        publisher.cleanup()


def _pause_lease_before_replace(table: Path, operation: str, barrier: Connection) -> None:
    runtime = _runtime_module()
    store = runtime.WorkerLeaseStore(table)
    old_grant = (
        store.reserve(requested_workers=4, effective_cpu_capacity=4, stage="first")
        if operation == "release" else None
    )
    original_replace = runtime.os.replace
    paused = False

    def replace(source, target, **kwargs):
        nonlocal paused
        if Path(target).name == table.name and not paused:
            paused = True
            barrier.send("staged")
            assert barrier.poll(10) and barrier.recv() == "resume"
        return original_replace(source, target, **kwargs)

    with barrier, patch.object(runtime.os, "replace", replace):
        if old_grant is None:
            result = store.reserve(requested_workers=4, effective_cpu_capacity=4, stage="first")
        else:
            result = store.release(old_grant.token)
        barrier.send(result)
        assert barrier.poll(10) and barrier.recv() == "stop"


def test_runtime_scope_installs_and_restores_the_worker_lease_path(
    tmp_path: Path,
) -> None:
    runtime = _runtime_module()
    snapshot = tmp_path / "demand.json"
    lease = tmp_path / "workers.json"

    assert runtime.current_worker_lease_path() is None
    with runtime.task_parallelism_runtime_scope(snapshot, lease):
        assert runtime.current_demand_snapshot_path() == snapshot
        assert runtime.current_worker_lease_path() == lease
        # Nested scopes without a lease table must not inherit the outer one.
        with runtime.task_parallelism_runtime_scope(tmp_path / "inner.json"):
            assert runtime.current_worker_lease_path() is None
        assert runtime.current_worker_lease_path() == lease
    assert runtime.current_demand_snapshot_path() is None
    assert runtime.current_worker_lease_path() is None


def test_lease_table_with_unknown_fields_is_treated_as_untrustworthy(
    tmp_path: Path,
) -> None:
    """A table written by another version must not be read as 'empty'."""

    runtime = _runtime_module()
    lease_path = tmp_path / "workers.json"
    lease_path.write_text(
        json.dumps(
            {
                "version": runtime.WORKER_LEASE_VERSION,
                "generation": 1,
                "leases": {
                    "row": {
                        "pid": 1,
                        "created": 0.0,
                        "touched": 0.0,
                        "workers": 4,
                        "stage": "test",
                        "effective_cpu": 8,
                        "future_field": "unknown",
                    }
                },
                "updated_monotonic_ns": 0,
            }
        ),
        encoding="utf-8",
    )
    assert runtime.read_worker_leases(lease_path) == ({}, True)
    grant = runtime.WorkerLeaseStore(lease_path).reserve(
        requested_workers=4, effective_cpu_capacity=8, stage="test"
    )
    assert (grant.workers, grant.state) == (1, "invalid")


@pytest.mark.parametrize(
    "fake_pid", [999_999, 1_000_000, 1_000_001, 1_500_000, 4_194_303]
)
def test_worker_lease_lifecycle_accepts_high_platform_pids_without_poisoning_siblings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_pid: int,
) -> None:
    """A valid OS PID must survive every real lease-table operation."""

    runtime = _runtime_module()
    monkeypatch.setattr(runtime, "_process_create_time", lambda _pid: 1234.0)
    monkeypatch.setattr(runtime, "_lease_owner_alive", lambda _pid, _created: True)
    publisher = runtime.OuterDemandPublisher(max_workers=8, parent_dir=tmp_path)
    store = runtime.WorkerLeaseStore(publisher.worker_lease_path)
    try:
        sibling = store.reserve(
            requested_workers=1,
            effective_cpu_capacity=8,
            stage="sibling",
            owner_pid=42,
        )
        grant = store.reserve(
            requested_workers=2,
            effective_cpu_capacity=8,
            stage="material",
            owner_pid=fake_pid,
        )
        leases, invalid = runtime.read_worker_leases(publisher.worker_lease_path)
        assert invalid is False
        assert grant.token in leases
        assert sibling.token in leases
        assert store.allowed_workers(grant.token) == 2
        assert store.release(grant.token) is True
        remaining, invalid_after_release = runtime.read_worker_leases(
            publisher.worker_lease_path
        )
        assert invalid_after_release is False
        assert grant.token not in remaining
        assert sibling.token in remaining
        assert store.release(sibling.token) is True
    finally:
        publisher.cleanup()
