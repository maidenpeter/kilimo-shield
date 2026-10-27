from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import RainfallSource
from .chirps import ChirpsClimateServSource
from .synthetic import SyntheticRainfallSource


def make_source(cfg: Config, source: str | None = None, allow_download: bool = True,
                log=print) -> RainfallSource:
    """Build the rainfall source named in config (or the override)."""
    name = source or cfg.rainfall.source
    if name == "chirps":
        repo = Path(cfg.root).parent
        return ChirpsClimateServSource(repo / "data" / "raw" / "chirps", allow_download, log)
    if name == "synthetic":
        return SyntheticRainfallSource(cfg.rainfall.synthetic_seed)
    raise ValueError(f"unknown rainfall source {name!r}")


__all__ = ["RainfallSource", "ChirpsClimateServSource", "SyntheticRainfallSource", "make_source"]
