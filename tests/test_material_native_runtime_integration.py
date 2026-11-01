"""Exercise material search and native export in a conflicting macOS runtime."""

from __future__ import annotations

from importlib.metadata import distribution
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS OpenMP library loading")
def test_material_search_can_export_with_a_separate_numba_openmp_runtime(tmp_path: Path) -> None:
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
        import zipfile
        import xml.etree.ElementTree as ET
        import numba
        import numpy as np

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

        import neroued_3mf as native
        builder = native.DocumentBuilder()
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)
        faces = np.array([[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]], dtype=np.uint32)
        # Cross the native writer's parallel serialization threshold.
        copies = 32768
        vertices = np.tile(vertices, (copies, 1))
        vertices[:, 0] += np.repeat(np.arange(copies, dtype=np.float32), 4) * 2
        faces = (faces[None, :, :] + 4 * np.arange(copies, dtype=np.uint32)[:, None, None]).reshape(-1, 3)
        object_id = builder.add_mesh_object('material result', vertices, faces)
        builder.add_build_item(object_id)
        native.write_to_file(sys.argv[2], builder.build(), native.WriteOptions())
        with zipfile.ZipFile(sys.argv[2]) as archive:
            models = [ET.fromstring(archive.read(name)) for name in archive.namelist() if name.endswith('.model')]
        triangles = [element for model in models for element in model.iter() if element.tag.endswith('}triangle')]
        assert len(triangles) == len(faces)
        print('material search and export complete')
    """)
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script, str(module_copy), str(tmp_path / "result.3mf")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "material search and export complete" in result.stdout
