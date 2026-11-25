"""Exercise native code paths that can load separate macOS OpenMP libraries."""

from __future__ import annotations

from importlib.metadata import distribution
from pathlib import Path
import os
import shutil
import subprocess
import sys
import textwrap

import pytest


def _write_large_native_3mf(output: Path) -> int:
    """Cross the native writer's parallel threshold with one valid mesh."""
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile

    import neroued_3mf as native
    import numpy as np

    copies = 32768
    tetrahedron = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
    tetrahedron_faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]], dtype=np.uint32)
    vertices = np.tile(tetrahedron, (copies, 1))
    vertices[:, 0] += np.repeat(np.arange(copies, dtype=np.float32), 4) * 2
    offsets = 4 * np.arange(copies, dtype=np.uint32)[:, None, None]
    triangles = (tetrahedron_faces + offsets).reshape(-1, 3)
    builder = native.DocumentBuilder()
    builder.add_build_item(builder.add_mesh_object("OpenMP regression", vertices, triangles))
    native.write_to_file(str(output), builder.build(), native.WriteOptions())
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        model = ET.fromstring(archive.read("3D/3dmodel.model"))
        assert len(model.findall(".//{*}triangle")) == len(triangles)
    return os.getpid()


@pytest.fixture
def clean_openmp_environment(tmp_path: Path) -> dict[str, str]:
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("OMP_", "KMP_", "GOMP_", "DYLD_", "OPENBLAS_"))
    }
    env["LUMINA_ENV_LOCAL_PATH"] = str(tmp_path / "absent.env")
    env["LUMINA_LOG_PATH"] = str(tmp_path / "backend.log")
    env["LUMINA_SETTINGS_PATH"] = str(tmp_path / "settings.json")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (
        str(Path(__file__).resolve().parent), env.get("PYTHONPATH"),
    )))
    return env


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS OpenMP library loading")
def test_source_startup_can_write_large_3mf(tmp_path: Path, clean_openmp_environment: dict[str, str]) -> None:
    """Exercise the normal api_server preflight and then export in its process."""
    script = textwrap.dedent("""
        import os
        import resource
        import sys
        from pathlib import Path

        import api_server
        from test_material_native_runtime_integration import _write_large_native_3mf

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        def export_after_startup(_env):
            from api.app import app

            _write_large_native_3mf(Path(sys.argv[1]))
            assert 'neroued_vectorizer' not in sys.modules
            assert os.environ['OMP_THREAD_LIMIT'] == '1'
            assert 'KMP_DUPLICATE_LIB_OK' not in os.environ

        api_server._run_server = export_after_startup
        sys.exit(api_server.main([]))
    """)
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script, str(tmp_path / "startup.3mf")],
        env=clean_openmp_environment, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS OpenMP library loading")
def test_reused_worker_slot_separates_vectorization_from_large_3mf(
    tmp_path: Path, clean_openmp_environment: dict[str, str],
) -> None:
    """Call the real vectorizer route between exports with worker recycling disabled."""
    script = textwrap.dedent("""
        import asyncio
        import io
        import os
        import resource
        import sys
        from pathlib import Path

        from fastapi.testclient import TestClient
        from PIL import Image
        import config
        from api.worker_pool import WorkerPoolManager
        from test_material_native_runtime_integration import _write_large_native_3mf

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        directory = Path(sys.argv[1])
        config.TEMP_DIR = str(directory)
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            assert asyncio.run(pool.submit(os.getenv, 'OMP_THREAD_LIMIT')) == '1'
            assert asyncio.run(pool.submit(os.getenv, 'KMP_DUPLICATE_LIB_OK')) is None
            first_pid = asyncio.run(pool.submit(_write_large_native_3mf, directory / 'first.3mf'))

            from api.app import create_app
            from api.dependencies import get_file_registry, get_worker_pool
            from api.file_registry import FileRegistry

            registry = FileRegistry()
            app = create_app()
            app.dependency_overrides[get_file_registry] = lambda: registry
            app.dependency_overrides[get_worker_pool] = lambda: pool
            image = Image.new('RGB', (48, 32), '#cc5511')
            image.paste('#ffffff', (0, 0, 24, 32))
            payload = io.BytesIO()
            image.save(payload, format='PNG')
            with TestClient(app, raise_server_exceptions=True) as client:
                response = client.post('/api/vectorize', files={'image': ('input.png', payload.getvalue(), 'image/png')})
                assert response.status_code == 200, response.text
                svg = client.get(response.json()['svg_url'])
                assert svg.status_code == 200 and b'<svg' in svg.content
            second_pid = asyncio.run(pool.submit(_write_large_native_3mf, directory / 'second.3mf'))
            third_pid = asyncio.run(pool.submit(_write_large_native_3mf, directory / 'third.3mf'))
            assert first_pid != second_pid == third_pid
        finally:
            pool.shutdown()
    """)
    env = {**clean_openmp_environment, "LUMINA_WORKER_MAX_TASKS_PER_CHILD": "0"}
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script, str(tmp_path)],
        env=env, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS OpenMP library loading")
def test_material_search_can_export_with_a_separate_numba_openmp_runtime(
    tmp_path: Path, clean_openmp_environment: dict[str, str],
) -> None:
    """Model a source environment whose Numba and 3MF wheels own separate libomp copies."""
    numba_dist = distribution("numba")
    writer_dist = distribution("neroued-3mf")
    omp_module = next(
        (numba_dist.locate_file(path) for path in numba_dist.files or ()
         if path.name.startswith("omppool.") and path.suffix == ".so"),
        None,
    )
    omp_library = next(
        (writer_dist.locate_file(path) for path in writer_dist.files or ()
         if path.name == "libomp.dylib"),
        None,
    )
    if omp_module is None or omp_library is None:
        pytest.skip("Native dependencies do not bundle the macOS OpenMP runtimes")
    if not shutil.which("install_name_tool") or not shutil.which("codesign"):
        pytest.skip("The macOS developer tools are required to prepare isolated test libraries")

    # Only alter copies inside tmp_path; installed wheels stay untouched.
    module_copy = tmp_path / omp_module.name
    library_copy = tmp_path / "libomp.dylib"
    shutil.copy2(omp_module, module_copy)
    shutil.copy2(omp_library, library_copy)
    dependencies = subprocess.check_output(["otool", "-L", str(module_copy)], text=True)
    original_reference = next(
        line.strip().split(" (", 1)[0]
        for line in dependencies.splitlines()[1:]
        if "libomp.dylib" in line
    )
    for command in (
        ["install_name_tool", "-id", str(library_copy), str(library_copy)],
        ["install_name_tool", "-change", original_reference, str(library_copy), str(module_copy)],
        ["codesign", "--force", "--sign", "-", str(library_copy)],
        ["codesign", "--force", "--sign", "-", str(module_copy)],
    ):
        subprocess.run(command, check=True, capture_output=True, text=True)

    script = textwrap.dedent("""
        import sys
        from pathlib import Path
        import numba
        import numpy as np
        from test_material_native_runtime_integration import _write_large_native_3mf

        # Make the alternate runtime available to Numba's normal lazy import.
        # Serial kernels should never initialize that process-wide thread pool.
        numba.np.ufunc.__path__.insert(0, str(Path(sys.argv[1]).parent))
        numba.config.THREADING_LAYER = 'omp'

        from core.material_dynamic_solver import build_dynamic_candidate_catalog, search_dynamic_catalog_exact
        colors = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8)
        recipes = np.array([[0] * 10, [1] * 10], dtype=np.int32)
        catalog = build_dynamic_candidate_catalog(colors, recipes, np.array([5, 10], dtype=np.int16), 10)
        result = search_dynamic_catalog_exact(colors, catalog, 5, 10)
        assert result.engine == 'numba'
        np.testing.assert_array_equal(result.cumulative_best_candidate_indices[:, -1], [0, 1])

        _write_large_native_3mf(Path(sys.argv[2]))
        print('material search and export complete')
    """)
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script, str(module_copy), str(tmp_path / "result.3mf")],
        env=clean_openmp_environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "material search and export complete" in result.stdout
