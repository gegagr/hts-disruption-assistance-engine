"""Load and validate the assumption registry."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from src.config.schema import Registry


class RegistryLoadError(Exception):
    """Raised when the registry YAML is missing, malformed, or invalid.

    Includes the full pydantic validation path so a finance reader can locate
    the offending entry (FR-029 edge case: missing/invalid assumption).
    """


def load_registry(path: str | Path = "config/registry.yaml") -> Registry:
    """Parse and validate the registry. Returns a frozen :class:`Registry`."""

    p = Path(path)
    if not p.exists():
        raise RegistryLoadError(f"Registry file not found: {p}")

    try:
        raw: Any = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryLoadError(f"Registry YAML parse error: {exc}") from exc

    if not isinstance(raw, dict):
        raise RegistryLoadError(
            f"Registry root must be a mapping, got {type(raw).__name__}"
        )

    try:
        return Registry.model_validate(raw)
    except ValidationError as exc:
        raise RegistryLoadError(_format_validation_error(exc)) from exc


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Registry validation failed:"]
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)
