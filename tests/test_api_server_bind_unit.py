"""API server bind configuration tests.

API 服务监听配置测试。
"""

from __future__ import annotations

import os

import pytest


def test_cli_keeps_server_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api_server
    import uvicorn

    calls: list[dict[str, str]] = []

    def unexpected_server(*args, **kwargs):
        raise AssertionError("CLI bypassed the server entry point")

    monkeypatch.setattr(uvicorn, "run", unexpected_server)
    monkeypatch.setenv("LUMINA_API_HOST", "127.0.0.1")
    monkeypatch.setenv("LUMINA_API_PORT", "18000")
    monkeypatch.setattr(
        api_server, "_run_server", lambda env: calls.append(dict(env)),
        raising=False,
    )
    assert api_server.main([]) == 0
    assert calls[0]["LUMINA_API_HOST"] == "127.0.0.1"
    assert calls[0]["LUMINA_API_PORT"] == "18000"


def test_macos_preflight_honors_local_openmp_settings(monkeypatch, tmp_path) -> None:
    import api_server
    from scripts import source_dependencies

    local_env = tmp_path / "local.env"
    local_env.write_text("OMP_NUM_THREADS=3\nOMP_THREAD_LIMIT=5\n", encoding="utf-8")
    monkeypatch.setattr(api_server.sys, "platform", "darwin")
    monkeypatch.setenv("LUMINA_ENV_LOCAL_PATH", str(local_env))
    monkeypatch.delenv("OMP_NUM_THREADS", raising=False)
    monkeypatch.setenv("OMP_THREAD_LIMIT", "2")

    def check_preflight() -> bool:
        assert os.environ["OMP_NUM_THREADS"] == "3"
        assert os.environ["OMP_THREAD_LIMIT"] == "2"
        return True

    monkeypatch.setattr(source_dependencies, "report_backend_dependencies", check_preflight)
    assert api_server.main(["--check-dependencies"]) == 0


def test_api_server_defaults_preserve_existing_development_bind() -> None:
    from api_server import _resolve_server_bind

    assert _resolve_server_bind({}) == ("0.0.0.0", 8000)


def test_desktop_can_bind_backend_to_an_isolated_loopback_port() -> None:
    from api_server import _resolve_server_bind

    assert _resolve_server_bind(
        {
            "LUMINA_API_HOST": "127.0.0.1",
            "LUMINA_API_PORT": "18000",
        }
    ) == ("127.0.0.1", 18000)


@pytest.mark.parametrize(
    "port",
    ["", "0", "80", "65536", "8000x", "8.0", " 8000 "],
)
def test_api_server_rejects_invalid_or_privileged_port(port: str) -> None:
    from api_server import _resolve_server_bind

    with pytest.raises(ValueError, match="LUMINA_API_PORT"):
        _resolve_server_bind({"LUMINA_API_PORT": port})


def test_api_server_rejects_unsupported_bind_override() -> None:
    from api_server import _resolve_server_bind

    with pytest.raises(ValueError, match="LUMINA_API_HOST"):
        _resolve_server_bind(
            {
                "LUMINA_API_HOST": "192.168.1.5",
                "LUMINA_API_PORT": "18000",
            }
        )
