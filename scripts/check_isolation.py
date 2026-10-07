"""Verify the project runs standalone: no module or path resolves outside the repo.

    python scripts/check_isolation.py
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import paths  # noqa: E402

FORBIDDEN = ("DATN-20225064", "lab-realtime", "realtime-data")


def main() -> int:
    problems: list[str] = []

    for name, value in vars(paths).items():
        if name.isupper() and isinstance(value, Path):
            if not value.resolve().is_relative_to(ROOT):
                problems.append(f"path {name} outside project: {value}")

    for package in ("core", "hap_shared"):
        module = importlib.import_module(package)
        for info in pkgutil.walk_packages(module.__path__, prefix=f"{package}."):
            try:
                importlib.import_module(info.name)
            except Exception as exc:  # report, keep scanning
                problems.append(f"import {info.name} failed: {type(exc).__name__}: {exc}")

    venv = Path(sys.prefix).resolve()
    for name, module in list(sys.modules.items()):
        origin = getattr(module, "__file__", None) or ""
        if any(token in origin for token in FORBIDDEN):
            problems.append(f"module {name} loaded from {origin}")
        elif origin and not (Path(origin).resolve().is_relative_to(ROOT) or Path(origin).resolve().is_relative_to(venv)
                             or Path(origin).resolve().is_relative_to(Path(sys.base_prefix).resolve())):
            problems.append(f"module {name} loaded from outside project/venv: {origin}")

    for line in problems:
        print("FAIL", line)
    print(f"{'OK' if not problems else 'FAILED'}: checked {len(sys.modules)} modules")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
