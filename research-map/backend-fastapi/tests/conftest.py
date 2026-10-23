"""Shared pytest setup for the research-map backend.

The real station registry lives in the gitignored data/ folder, so CI has no copy.
Point every test at a small tracked fixture (NB1 + 13 synthetic stations) so the
suite runs the same locally and in CI.  Must run before ``app.domain`` is imported.
"""
import os
from pathlib import Path

os.environ["STATION_REGISTRY_PATH"] = str(Path(__file__).parent / "fixtures" / "station_coordinates.csv")
