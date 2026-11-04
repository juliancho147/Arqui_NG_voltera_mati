"""Smoke test del esqueleto del paquete runner_blockchain."""
import runner_blockchain


def test_package_importable_con_version():
    assert isinstance(runner_blockchain.__version__, str)
    assert runner_blockchain.__version__
