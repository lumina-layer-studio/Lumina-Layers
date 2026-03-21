"""Unit tests for Health and LUT list endpoints.

Validates:
- GET /api/health returns correct structure and values (Requirement 11)
- GET /api/health reflects Worker Pool state (Requirements 6.1, 6.2)
- GET /api/lut/list returns sorted LUT dictionary (Requirement 10)
"""

from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_worker_pool
from api.worker_pool import WorkerPoolManager

client: TestClient = TestClient(app)


# =========================================================================
# 1. Health endpoint (GET /api/health) - Requirement 11
# =========================================================================


class TestHealthEndpoint:
    """Verify the health check endpoint returns correct structure and values."""

    def test_health_returns_200(self) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200

    def test_health_contains_required_fields(self) -> None:
        data: dict = client.get("/api/health").json()
        assert "status" in data
        assert "version" in data
        assert "uptime_seconds" in data
        assert "worker_pool" in data

    def test_health_status_is_ok(self) -> None:
        data: dict = client.get("/api/health").json()
        assert data["status"] == "ok"

    def test_health_version_is_2_0(self) -> None:
        data: dict = client.get("/api/health").json()
        assert data["version"] == "2.0"

    def test_health_uptime_is_non_negative_float(self) -> None:
        data: dict = client.get("/api/health").json()
        uptime = data["uptime_seconds"]
        assert isinstance(uptime, float)
        assert uptime >= 0.0

    def test_health_worker_pool_contains_required_fields(self) -> None:
        data: dict = client.get("/api/health").json()
        wp = data["worker_pool"]
        assert "healthy" in wp
        assert "max_workers" in wp

    def test_health_worker_pool_healthy_is_bool(self) -> None:
        data: dict = client.get("/api/health").json()
        assert isinstance(data["worker_pool"]["healthy"], bool)

    def test_health_worker_pool_max_workers_is_positive_int(self) -> None:
        data: dict = client.get("/api/health").json()
        mw = data["worker_pool"]["max_workers"]
        assert isinstance(mw, int)
        assert mw >= 1


# =========================================================================
# 2. Health endpoint Worker Pool state (Requirements 6.1, 6.2)
# =========================================================================


class TestHealthWorkerPoolState:
    """Verify health endpoint reflects Worker Pool alive/dead states via dependency override.
    通过依赖注入覆盖验证健康检查端点正确反映 Worker Pool 的存活/停止状态。
    """

    def _make_client_with_pool(self, pool: WorkerPoolManager) -> TestClient:
        """Create a TestClient with a custom WorkerPoolManager injected.
        创建注入自定义 WorkerPoolManager 的 TestClient。
        """
        app.dependency_overrides[get_worker_pool] = lambda: pool
        test_client = TestClient(app)
        return test_client

    def teardown_method(self) -> None:
        """Remove only this class's worker pool override after each test.
        每个测试后仅移除本类设置的 worker pool 覆盖，避免影响其他模块。
        """
        app.dependency_overrides.pop(get_worker_pool, None)

    def test_pool_alive_reports_healthy_true(self) -> None:
        """When pool is started (is_alive=True), healthy should be True.
        当进程池已启动时，healthy 应为 True。
        """
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        try:
            tc = self._make_client_with_pool(pool)
            data = tc.get("/api/health").json()
            assert data["worker_pool"]["healthy"] is True
        finally:
            pool.shutdown(wait=False)

    def test_pool_not_started_reports_healthy_false(self) -> None:
        """When pool is never started (is_alive=False), healthy should be False.
        当进程池未启动时，healthy 应为 False。
        """
        pool = WorkerPoolManager(max_workers=2)
        # Do NOT call pool.start()
        tc = self._make_client_with_pool(pool)
        data = tc.get("/api/health").json()
        assert data["worker_pool"]["healthy"] is False

    def test_pool_shutdown_reports_healthy_false(self) -> None:
        """When pool is started then shut down, healthy should be False.
        当进程池启动后关闭时，healthy 应为 False。
        """
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        pool.shutdown(wait=True)
        tc = self._make_client_with_pool(pool)
        data = tc.get("/api/health").json()
        assert data["worker_pool"]["healthy"] is False

    def test_pool_alive_max_workers_matches(self) -> None:
        """max_workers in response should match the injected pool's value.
        响应中的 max_workers 应与注入的进程池值一致。
        """
        pool = WorkerPoolManager(max_workers=3)
        pool.start()
        try:
            tc = self._make_client_with_pool(pool)
            data = tc.get("/api/health").json()
            assert data["worker_pool"]["max_workers"] == 3
        finally:
            pool.shutdown(wait=False)

    def test_pool_not_started_max_workers_still_positive(self) -> None:
        """Even when pool is not started, max_workers should be a positive int.
        即使进程池未启动，max_workers 仍应为正整数。
        """
        pool = WorkerPoolManager(max_workers=4)
        tc = self._make_client_with_pool(pool)
        data = tc.get("/api/health").json()
        mw = data["worker_pool"]["max_workers"]
        assert isinstance(mw, int)
        assert mw == 4
        assert mw >= 1


# =========================================================================
# 3. LUT list endpoint (GET /api/lut/list) - Requirement 10
# =========================================================================


class TestLUTListEndpoint:
    """Verify the LUT list endpoint returns correct structure and sorted keys."""

    def test_lut_list_returns_200(self) -> None:
        response = client.get("/api/lut/list")
        assert response.status_code == 200

    def test_lut_list_contains_required_fields(self) -> None:
        data: dict = client.get("/api/lut/list").json()
        assert "luts" in data

    def test_lut_list_luts_is_list(self) -> None:
        data: dict = client.get("/api/lut/list").json()
        assert isinstance(data["luts"], list)

    def test_lut_list_items_have_required_fields(self) -> None:
        data: dict = client.get("/api/lut/list").json()
        for item in data["luts"]:
            assert "name" in item
            assert "color_mode" in item
            assert "path" in item

    def test_lut_list_names_sorted_alphabetically(self) -> None:
        data: dict = client.get("/api/lut/list").json()
        names = [item["name"] for item in data["luts"]]
        assert names == sorted(names)
