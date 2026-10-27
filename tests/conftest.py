from pathlib import Path

import pytest

from agroshield_pricing.config import load_config

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def cfg():
    return load_config(REPO / "config")


@pytest.fixture
def config_copy(tmp_path):
    """A writable copy of config/ so a test can edit one file."""
    dst = tmp_path / "config"
    dst.mkdir()
    for f in (REPO / "config").glob("*.yaml"):
        (dst / f.name).write_bytes(f.read_bytes())
    return dst
