"""Constitution Principle IV — layer boundaries enforced by import discipline.

Rules:
- ``src/ui/`` and ``src/export/`` MUST NOT import ``pandas``, ``numpy``, or
  ``src.data`` (presentation never computes; never touches raw facts).
- ``src/engine/`` MUST NOT import ``src.ui``, ``src.export``, or
  ``streamlit``.
- ``src/data/`` MUST NOT import ``src.engine``, ``src.ui``, or ``src.export``.

The test walks every .py file with :mod:`ast` and fails on the first
violation, naming the file and the offending import.
"""
from __future__ import annotations

import ast
from pathlib import Path
from collections.abc import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"


def _py_files(subdir: str) -> Iterable[Path]:
    return sorted((SRC / subdir).rglob("*.py"))


def _imports(path: Path) -> set[str]:
    """All module names imported by *path* (top-level + from-imports)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names.add(mod)
    return names


def _has_forbidden(imports: set[str], forbidden: Iterable[str]) -> str | None:
    for imp in imports:
        for f in forbidden:
            if imp == f or imp.startswith(f + "."):
                return imp
    return None


def _check_layer(subdir: str, forbidden: tuple[str, ...]) -> None:
    violations: list[str] = []
    for path in _py_files(subdir):
        imps = _imports(path)
        offender = _has_forbidden(imps, forbidden)
        if offender:
            violations.append(f"{path.relative_to(REPO_ROOT)}: imports {offender}")
    if violations:
        pytest.fail(
            f"Layer-boundary violation in src/{subdir}/:\n  - "
            + "\n  - ".join(violations)
        )


def test_ui_does_not_compute() -> None:
    _check_layer("ui", forbidden=("pandas", "numpy", "src.data"))


def test_export_does_not_touch_raw_data() -> None:
    _check_layer("export", forbidden=("pandas", "numpy", "src.data"))


def test_engine_does_not_import_presentation() -> None:
    _check_layer(
        "engine",
        forbidden=("src.ui", "src.export", "streamlit"),
    )


def test_data_does_not_import_engine_or_presentation() -> None:
    _check_layer(
        "data",
        forbidden=("src.engine", "src.ui", "src.export"),
    )
