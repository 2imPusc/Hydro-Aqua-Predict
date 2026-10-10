"""Shared pytest hooks."""
import pytest

from core import paths

# Local, gitignored inputs that some tests read (see docs/data-policy.md).
REQUIRED_DATA = [
    paths.clean_data("haiphong"),
    paths.clean_data("quangninh"),
    paths.STATION_COORDINATES,
    paths.WATER_SHAPEFILE,
]


def pytest_collection_modifyitems(config, items):
    missing = [str(p) for p in REQUIRED_DATA if not p.exists()]
    if not missing:
        return
    skip = pytest.mark.skip(reason=f"local data/ missing: {missing[0]} (restore per docs/data-policy.md)")
    for item in items:
        if "requires_data" in item.keywords:
            item.add_marker(skip)
