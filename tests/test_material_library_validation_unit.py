"""Saved-material picker entries must remain usable after filesystem changes."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil

import pytest

from core import material_lut_synthesis
from core.single_stage import material_files, material_library, material_registry_client


def _stage_a_bytes() -> bytes:
    return json.dumps({
        "parameters": {
            "channels": [{"E": [0.2, 0.3, 0.4], "k": [1.0, 1.1, 1.2]}],
            "substrates": [
                {"substrate_id": "white", "C0": [0.99, 0.98, 0.97]},
                {"substrate_id": "black", "C0": [0.01, 0.02, 0.03]},
            ],
        },
    }).encode("utf-8")


def _write_material(root: Path, name: str, stage_name: str = "stage_A_parameters.json") -> tuple[Path, Path]:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "material.json"
    archive.write_text(json.dumps({
        "material_name": name.rsplit("/", 1)[-1],
        "stage_a_params_file": stage_name,
        "material_summary": {"estimated_rgb": [120, 130, 140]},
    }), encoding="utf-8")
    stage = directory / stage_name.replace("\\", "/")
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_bytes(_stage_a_bytes())
    return archive, stage


def _listed_names(root: Path) -> set[str]:
    return {
        item["directory_name"]
        for item in material_library.list_saved_stage_a_material_archives(materials_dir=str(root))
    }


@pytest.fixture(autouse=True)
def local_library_only(monkeypatch: pytest.MonkeyPatch):
    # Remote catalog enrichment is independent of local archive availability.
    monkeypatch.setattr(material_registry_client, "_official_material_registry_metadata_by_signature", lambda: {})
    material_files.invalidate_material_library_cache()
    yield
    material_files.invalidate_material_library_cache()


@pytest.mark.parametrize("damage", ["missing", "invalid_json", "missing_vectors", "non_finite", "unsafe_path"])
def test_material_library_excludes_archives_the_solver_cannot_load(tmp_path: Path, damage: str) -> None:
    _write_material(tmp_path, "Brand/Valid")
    archive, stage = _write_material(tmp_path, "Brand/Invalid")
    if damage == "missing":
        stage.unlink()
    elif damage == "invalid_json":
        stage.write_text("broken JSON", encoding="utf-8")
    elif damage == "missing_vectors":
        stage.write_text('{"parameters": {}}', encoding="utf-8")
    elif damage == "non_finite":
        payload = json.loads(stage.read_bytes())
        payload["parameters"]["channels"][0]["E"][1] = float("nan")
        stage.write_text(json.dumps(payload), encoding="utf-8")
    else:
        payload = json.loads(archive.read_bytes())
        payload["stage_a_params_file"] = "../outside.json"
        archive.write_text(json.dumps(payload), encoding="utf-8")
        # A valid default file must not mask an invalid declared path.
        assert stage.is_file()

    with pytest.raises((ValueError, FileNotFoundError)):
        material_lut_synthesis.load_material_params("Brand/Invalid", materials_dir=str(tmp_path))
    assert _listed_names(tmp_path) == {"Brand/Valid"}


@pytest.mark.parametrize("internal", ["_SyNc", "_solver_cache"])
def test_material_discovery_excludes_internal_segments_at_any_depth(tmp_path: Path, internal: str) -> None:
    visible = "Brand/_sync-copy/Visible"
    hidden = f"Brand/Nested/{internal}/Hidden"
    _write_material(tmp_path, visible)
    _write_material(tmp_path, hidden)
    _write_material(tmp_path, visible + "/runs/history")

    assert set(material_files._discover_saved_material_dirs(tmp_path)) == {tmp_path / visible}
    assert set(material_files._discover_saved_material_dirs(tmp_path, include_internal=True)) == {
        tmp_path / visible, tmp_path / hidden,
    }
    assert _listed_names(tmp_path) == {visible}


@pytest.mark.parametrize("use_alias", [False, True])
def test_default_loader_rejects_nested_internal_paths_but_project_root_restores_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_alias: bool,
) -> None:
    internal = "Brand/_sync/Material"
    _write_material(tmp_path, internal)
    selected = internal
    if use_alias:
        try:
            (tmp_path / "Alias").symlink_to(tmp_path / internal, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("Directory symlinks are unavailable on this filesystem")
        selected = "Alias"
    monkeypatch.setattr(material_lut_synthesis, "MATERIALS_DIR", str(tmp_path))

    with pytest.raises(ValueError, match="internal library directory"):
        material_lut_synthesis.load_material_params(selected)
    loaded = material_lut_synthesis.load_material_params(selected, materials_dir=str(tmp_path))
    assert loaded.directory_name == selected
    assert loaded.name == "Material"


@pytest.mark.parametrize("damage", ["stage_deleted", "stage_corrupt", "archive_deleted", "archive_corrupt", "directory_deleted"])
def test_cached_material_disappears_when_broken_and_reappears_when_repaired(tmp_path: Path, damage: str) -> None:
    archive, stage = _write_material(tmp_path, "Brand/Material")
    archive_bytes, stage_bytes = archive.read_bytes(), stage.read_bytes()
    assert _listed_names(tmp_path) == {"Brand/Material"}
    if damage == "stage_deleted":
        stage.unlink()
    elif damage == "stage_corrupt":
        stage.write_text("broken Stage A", encoding="utf-8")
    elif damage == "archive_deleted":
        archive.unlink()
    elif damage == "archive_corrupt":
        archive.write_text("broken archive", encoding="utf-8")
    else:
        shutil.rmtree(archive.parent)

    assert _listed_names(tmp_path) == set()
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(archive_bytes)
    stage.write_bytes(stage_bytes)
    assert _listed_names(tmp_path) == {"Brand/Material"}


def test_cached_incomplete_material_appears_after_declared_nested_stage_file_is_created(tmp_path: Path) -> None:
    _archive, stage = _write_material(tmp_path, "Brand/Material", "calibration\\fitted.json")
    stage_bytes = stage.read_bytes()
    shutil.rmtree(stage.parent)
    assert _listed_names(tmp_path) == set()

    stage.parent.mkdir()
    stage.write_bytes(stage_bytes)
    assert _listed_names(tmp_path) == {"Brand/Material"}


def test_cached_invalid_archive_appears_after_its_json_is_repaired(tmp_path: Path) -> None:
    archive, _stage = _write_material(tmp_path, "Brand/Material")
    original = archive.read_bytes()
    archive.write_text("invalid", encoding="utf-8")
    assert _listed_names(tmp_path) == set()
    archive.write_bytes(original)
    assert _listed_names(tmp_path) == {"Brand/Material"}


def test_cached_library_discovers_new_materials_below_existing_empty_groups(tmp_path: Path) -> None:
    (tmp_path / "Brand/Nested").mkdir(parents=True)
    assert _listed_names(tmp_path) == set()
    _write_material(tmp_path, "Brand/Nested/Material")
    assert _listed_names(tmp_path) == {"Brand/Nested/Material"}


@pytest.mark.parametrize("had_material", [False, True], ids=["new", "restored"])
def test_material_cache_detects_new_children_with_unchanged_directory_stats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, had_material: bool,
) -> None:
    group = tmp_path / "Brand/Nested"
    group.mkdir(parents=True)
    name = "Brand/Nested/Material"
    if had_material:
        archive, _ = _write_material(tmp_path, name)
        assert _listed_names(tmp_path) == {name}
        shutil.rmtree(archive.parent)

    read_path_state = material_files._material_library_path_state
    stable_states = {path: read_path_state(path) for path in (tmp_path, group.parent, group)}

    def path_state_with_unchanged_group_stats(path: Path) -> tuple[int, ...] | None:
        if path in stable_states:
            return stable_states[path]
        return read_path_state(path)

    monkeypatch.setattr(material_files, "_material_library_path_state", path_state_with_unchanged_group_stats)
    assert _listed_names(tmp_path) == set()
    _write_material(tmp_path, name)
    assert _listed_names(tmp_path) == {name}


@pytest.mark.parametrize("blocked_directory", ["Brand", "Brand/Material"])
def test_material_cache_recovers_after_directory_access_is_restored(
    tmp_path: Path, blocked_directory: str,
) -> None:
    _write_material(tmp_path, "Brand/Material")
    blocked = tmp_path / blocked_directory
    original_mode = blocked.stat().st_mode
    assert _listed_names(tmp_path) == {"Brand/Material"}
    try:
        blocked.chmod(0)
        try:
            list(blocked.iterdir())
        except PermissionError:
            pass
        else:
            pytest.skip("The current account bypasses directory permission restrictions")
        assert _listed_names(tmp_path) == set()
    finally:
        blocked.chmod(original_mode)

    assert _listed_names(tmp_path) == {"Brand/Material"}


def test_cache_follows_changed_stage_a_declaration_and_the_new_file(tmp_path: Path) -> None:
    archive, _stage = _write_material(tmp_path, "Brand/Material")
    assert _listed_names(tmp_path) == {"Brand/Material"}
    custom = archive.parent / "calibration/new.json"
    custom.parent.mkdir()
    custom.write_bytes(_stage_a_bytes())
    payload = json.loads(archive.read_bytes())
    payload["stage_a_params_file"] = "calibration/new.json"
    archive.write_text(json.dumps(payload), encoding="utf-8")

    [item] = material_library.list_saved_stage_a_material_archives(materials_dir=str(tmp_path))
    assert Path(item["stage_a_params_path"]) == custom
    custom.unlink()
    assert _listed_names(tmp_path) == set()


def test_unchanged_material_cache_does_not_reread_json_or_revalidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_material(tmp_path, "Brand/Material")
    assert _listed_names(tmp_path) == {"Brand/Material"}

    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("unchanged material cache must use filesystem metadata only")

    monkeypatch.setattr(Path, "read_text", unexpected_read)
    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    monkeypatch.setattr(material_lut_synthesis, "load_material_params", unexpected_read)
    assert _listed_names(tmp_path) == {"Brand/Material"}


def test_usable_material_survives_malformed_optional_display_summaries(tmp_path: Path) -> None:
    archive, _stage = _write_material(tmp_path, "Brand/Material")
    payload = json.loads(archive.read_bytes())
    payload.update({"material_summary": ["damaged"], "fit_summary": ["damaged"]})
    archive.write_text(json.dumps(payload), encoding="utf-8")

    loaded = material_lut_synthesis.load_material_params("Brand/Material", materials_dir=str(tmp_path))
    assert loaded.E.tolist() == [0.2, 0.3, 0.4]
    [item] = material_library.list_saved_stage_a_material_archives(materials_dir=str(tmp_path))
    assert item["directory_name"] == "Brand/Material"
    assert item["estimated_rgb"] == []
    assert item["mean_delta_e"] is None


def test_usable_material_survives_malformed_optional_validation_summary(tmp_path: Path) -> None:
    archive, _stage = _write_material(tmp_path, "Brand/Material")
    payload = json.loads(archive.read_bytes())
    payload["fit_summary"] = {"overall_validation": ["damaged"]}
    archive.write_text(json.dumps(payload), encoding="utf-8")

    [item] = material_library.list_saved_stage_a_material_archives(materials_dir=str(tmp_path))
    assert item["directory_name"] == "Brand/Material"
    assert item["estimated_rgb"] == [120, 130, 140]
    assert item["mean_delta_e"] is None


def test_filtered_archive_logs_relative_directory_and_validation_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    _archive, stage = _write_material(tmp_path, "Brand/Incomplete")
    stage.unlink()
    logger = logging.getLogger("lumina.core.single_stage.material_library")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.DEBUG, logger=logger.name)
    try:
        assert _listed_names(tmp_path) == set()
    finally:
        logger.removeHandler(caplog.handler)

    records = [record for record in caplog.records if getattr(record, "event", None) == "material_library_archive_skipped"]
    assert records
    record = records[-1]
    assert record.directory_name == "Brand/Incomplete"
    assert record.error_type == "ValueError"
    assert "stage_a_params_file" in record.error_message
    assert str(tmp_path) not in record.error_message
