import pytest

import main


@pytest.mark.unit
def test_patch_asscalar():
    class Dummy:
        def item(self):
            return 42

    assert main.patch_asscalar(Dummy()) == 42


@pytest.mark.unit
def test_find_available_port_returns_int(free_port: int):
    port = main.find_available_port(start_port=free_port, max_attempts=10)
    assert isinstance(port, int)
    assert port >= free_port
