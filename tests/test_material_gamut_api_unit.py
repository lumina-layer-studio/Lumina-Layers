"""API tests for material gamut coverage and the cache overview endpoints.

耗材色域覆盖与缓存概览端点的 API 测试。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from core.material_color_solver import MaterialParams
from core.material_dynamic_solver import DynamicMaterialCandidateError

_PREFIX = "/api/extractor"


def _mat(name: str, e: tuple[float, float, float], k: float) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(e, dtype=np.float64),
        k=np.asarray((k, k, k), dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray([int(round(255 * c)) for c in e], dtype=np.uint8),
    )


_PALETTE = {
    "white": _mat("White", (0.95, 0.95, 0.95), 0.5),
    "red": _mat("Red", (0.70, 0.05, 0.05), 4.0),
    "blue": _mat("Blue", (0.05, 0.10, 0.70), 4.0),
}


@pytest.fixture
def router_logs(caplog: pytest.LogCaptureFixture):
    """Attach caplog to the router logger, which does not propagate."""
    target = logging.getLogger("lumina.api.routers.single_stage")
    target.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target.name)
    yield caplog
    target.removeHandler(caplog.handler)


def _events(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if getattr(record, "event", None) == name]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "api.routers.single_stage.load_multiple_materials",
        lambda names: [_PALETTE[name] for name in names],
    )
    return TestClient(create_app())


def _fixed_form(**overrides: object) -> dict[str, str]:
    form = {
        "material_directory_names": json.dumps(["white", "red", "blue"]),
        "layer_mode": "fixed",
        "layer_count": "5",
        "layer_height_mm": "0.08",
        "substrate": "white",
    }
    form.update({key: str(value) for key, value in overrides.items()})
    return form


def _dynamic_form(**overrides: object) -> dict[str, str]:
    form = {
        "material_directory_names": json.dumps(["white", "red", "blue"]),
        "layer_mode": "dynamic",
        "min_layer_count": "5",
        "max_layer_count": "6",
        "layer_height_mm": "0.08",
        "substrate": "white",
        "backing_material_directory_name": "white",
    }
    form.update({key: str(value) for key, value in overrides.items()})
    return form


def test_fixed_coverage_samples_in_memory_and_reports_exact_small_palette(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.post(f"{_PREFIX}/material-gamut/coverage", data=_fixed_form())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["layer_mode"] == "fixed"
    assert body["cell_size_delta_e"] == 5.0
    assert 0 < body["coverage"]["percent"] < 100
    assert body["coverage"]["reached_cell_count"] <= body["coverage"]["reference_cell_count"]
    assert body["source"] == {
        "kind": "quick_sample",
        "candidate_budget": 1_048_576,
        "is_complete": True,  # 3**5 stacks fit inside the budget
        "was_cached": False,
    }
    assert body["layer_cap_coverage"] == []
    groups = body["accuracy"]["groups"]
    assert [group["group"] for group in groups] == ["all", "neutral", "dark", "skin", "vivid"]
    assert all(group["mean_delta_e"] >= 0 for group in groups)
    assert 0 <= body["accuracy"]["darkest_lightness"] < body["accuracy"]["lightest_lightness"] <= 100
    assert body["color_count"] == body["coverage_stats"]["entry_count"]
    assert len(body["lab_points_3d"]) == body["coverage_stats"]["plotted_point_count"]
    assert not any(tmp_path.rglob("*.npz")), "fixed coverage must not write caches"


def test_dynamic_coverage_reports_monotonic_layer_caps_and_saves_catalog(
    client: TestClient, tmp_path: Path
) -> None:
    first = client.post(f"{_PREFIX}/material-gamut/coverage", data=_dynamic_form())
    second = client.post(f"{_PREFIX}/material-gamut/coverage", data=_dynamic_form())

    assert first.status_code == 200, first.text
    body = first.json()
    caps = body["layer_cap_coverage"]
    assert [cap["layer_count"] for cap in caps] == [5, 6]
    percents = [cap["coverage"]["percent"] for cap in caps]
    assert percents == sorted(percents)
    assert body["coverage"] == caps[-1]["coverage"]
    assert body["source"]["kind"] == "dynamic_catalog"
    assert body["source"]["was_cached"] is False
    assert body["backing_material_directory_name"] == "white"
    assert second.json()["source"]["was_cached"] is True
    assert second.json()["coverage"] == body["coverage"]


def test_contributions_list_every_material_with_consistent_drop(client: TestClient) -> None:
    response = client.post(f"{_PREFIX}/material-gamut/contributions", data=_fixed_form())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_complete"] is True
    assert [item["directory_name"] for item in body["items"]] == ["white", "red", "blue"]
    for item in body["items"]:
        expected = round(body["baseline"]["percent"] - item["coverage_without"]["percent"], 2)
        assert item["drop_percent"] == pytest.approx(expected)
        assert item["drop_percent"] >= 0  # exact enumeration never gains coverage
        assert len(item["accuracy_without"]["groups"]) == 5
        assert item["largest_loss_group"] in {"neutral", "dark", "skin", "vivid"}
        baseline_group = next(
            group for group in body["baseline_accuracy"]["groups"]
            if group["group"] == item["largest_loss_group"]
        )
        without_group = next(
            group for group in item["accuracy_without"]["groups"]
            if group["group"] == item["largest_loss_group"]
        )
        assert item["largest_loss_delta_e"] == pytest.approx(
            without_group["mean_delta_e"] - baseline_group["mean_delta_e"], abs=0.02
        )


def test_overview_prepare_and_delete_dynamic_cache_round_trip(
    client: TestClient, router_logs: pytest.LogCaptureFixture
) -> None:
    before = client.post(f"{_PREFIX}/material-cache/overview", data=_dynamic_form()).json()
    assert before["layer_mode"] == "dynamic"
    assert before["dynamic"]["is_ready"] is False
    assert before["dynamic"]["missing_layer_counts"] == [5, 6]

    prepared = client.post(f"{_PREFIX}/material-dynamic-cache/prepare", data=_dynamic_form())
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["built"] is True
    assert prepared.json()["dynamic"]["is_ready"] is True
    assert prepared.json()["dynamic"]["saved_layer_counts"] == [5, 6]
    assert _events(router_logs, "material_dynamic_cache_prepare_done")

    again = client.post(f"{_PREFIX}/material-dynamic-cache/prepare", data=_dynamic_form())
    assert again.json()["built"] is False

    deleted = client.post(f"{_PREFIX}/material-dynamic-cache/delete", data=_dynamic_form())
    assert deleted.json()["deleted"] is True
    after = client.post(f"{_PREFIX}/material-cache/overview", data=_dynamic_form()).json()
    assert after["dynamic"]["is_ready"] is False
    assert after["dynamic"]["saved_layer_counts"] == []


def test_dynamic_prepare_is_invisible_to_fixed_layer_mode(client: TestClient) -> None:
    client.post(f"{_PREFIX}/material-dynamic-cache/prepare", data=_dynamic_form())

    overview = client.post(f"{_PREFIX}/material-cache/overview", data=_fixed_form())

    assert overview.status_code == 200, overview.text
    assert overview.json()["fixed"]["saved_runtime_budgets"] == []
    coverage = client.post(f"{_PREFIX}/material-gamut/coverage", data=_fixed_form()).json()
    assert coverage["source"]["kind"] == "quick_sample"
    assert coverage["source"]["was_cached"] is False


@pytest.mark.parametrize(
    ("path", "form", "fragment"),
    [
        ("material-gamut/coverage", _fixed_form(layer_mode="hybrid"), "layer_mode"),
        ("material-gamut/coverage", _fixed_form(layer_count=11), "layer_count"),
        ("material-gamut/coverage", _dynamic_form(min_layer_count=7), "min_layer_count"),
        (
            "material-gamut/coverage",
            _dynamic_form(backing_material_directory_name="green"),
            "backing_material_directory_name",
        ),
        (
            "material-gamut/contributions",
            _fixed_form(material_directory_names=json.dumps(["red", "red"])),
            "repeat",
        ),
        ("material-dynamic-cache/prepare", _fixed_form(), "dynamic"),
        ("material-dynamic-cache/delete", _fixed_form(), "dynamic"),
        ("material-cache/overview", _dynamic_form(max_layer_count=None), "max_layer_count"),
    ],
)
def test_invalid_combinations_are_rejected_with_422(
    client: TestClient, path: str, form: dict[str, str], fragment: str
) -> None:
    form = {key: value for key, value in form.items() if value != "None"}
    response = client.post(f"{_PREFIX}/{path}", data=form)

    assert response.status_code == 422, response.text
    assert fragment in json.dumps(response.json())


def test_unexpected_core_failure_maps_to_500_with_structured_log(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    router_logs: pytest.LogCaptureFixture,
) -> None:
    def explode(*_args, **_kwargs):
        raise RuntimeError("catalog storage offline")

    monkeypatch.setattr("api.routers.single_stage.compute_dynamic_layer_gamut", explode)
    response = client.post(f"{_PREFIX}/material-gamut/coverage", data=_dynamic_form())

    assert response.status_code == 500
    assert "catalog storage offline" not in response.text
    failed = _events(router_logs, "material_gamut_coverage_failed")
    assert failed and failed[0].error_type == "RuntimeError"


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (DynamicMaterialCandidateError("private diagnostic", layer_count=6,
                                      phase="dynamic_catalog_cache_lock"), 503,
         "dynamic_material_solver_unavailable"),
        (ValueError("private diagnostic"), 500, None),
        (TypeError("private diagnostic"), 500, None),
    ],
)
def test_compute_failures_use_safe_domain_error_mapping(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
    failure: Exception, status: int, code: str | None,
) -> None:
    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("api.routers.single_stage.compute_dynamic_layer_gamut", fail)
    response = client.post(f"{_PREFIX}/material-gamut/coverage", data=_dynamic_form())
    assert response.status_code == status
    assert "private diagnostic" not in response.text
    if code:
        assert response.json()["detail"]["code"] == code


@pytest.mark.parametrize("path", [
    "material-gamut/coverage", "material-gamut/contributions",
    "material-dynamic-cache/prepare", "material-dynamic-cache/delete",
])
def test_heavy_material_requests_reject_a_busy_build_queue_with_retryable_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str,
    router_logs: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("api.routers.single_stage._RUNTIME_BUILD_GLOBAL_SEMAPHORE", threading.BoundedSemaphore(0))
    monkeypatch.setattr("api.routers.single_stage._MATERIAL_COMPUTE_QUEUE_TIMEOUT_SECONDS", 0.01)
    response = client.post(f"{_PREFIX}/{path}", data=_dynamic_form())
    assert response.status_code == 503
    assert response.json()["detail"]["stage"] == "material_compute_queue"
    assert response.json()["detail"]["code"] == "dynamic_material_solver_unavailable"
    failures = [record for record in router_logs.records if getattr(record, "event", "").endswith("_failed")]
    assert failures and failures[-1].levelno == logging.WARNING


def test_failed_computation_releases_its_build_slot(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    semaphore = threading.BoundedSemaphore(1)
    monkeypatch.setattr("api.routers.single_stage._RUNTIME_BUILD_GLOBAL_SEMAPHORE", semaphore)

    def fail(*_args, **_kwargs):
        assert not semaphore.acquire(blocking=False), "the build must hold its slot"
        raise RuntimeError("test failure")

    monkeypatch.setattr("api.routers.single_stage.compute_dynamic_layer_gamut", fail)
    assert client.post(f"{_PREFIX}/material-gamut/coverage", data=_dynamic_form()).status_code == 500
    assert semaphore.acquire(blocking=False), "failed work must release its slot"
    semaphore.release()
