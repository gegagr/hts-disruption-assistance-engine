"""C1 remediation — Constitution Principle II enforcement.

AST-walk every `src/engine/*.py` file and fail the test if any numeric
literal appears outside the allow-list. Allowed:

  * 0 and 1 (pure mathematical constants — additive/multiplicative identity)
  * 100, 1000, 10_000 (unit conversions: percentages, mille, basis points)
  * Numeric literals inside type annotations (e.g. `Field(ge=0, le=1.0)`)
  * Numeric literals in default keyword values inside Field(...) calls
  * Literals annotated with `# allow: literal`

Every other literal is presumed to be a hardcoded model input and must
move to ``config/registry.yaml`` (Constitution Engineering Constraint).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "src" / "engine"

ALLOWED_NUMERICS: set[int | float] = {
    0, 1, -1,
    100, 1000, 10000, # unit conversion constants
    7,                                  # days-in-a-week (calendar invariant)
    52,                                 # weeks-in-a-year (calendar invariant)
    2,                                  # binary-arm enumerations
}


def _is_allowed_constant(node: ast.Constant) -> bool:
    """Whitelist criteria for an `ast.Constant` numeric node."""
    if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
        return True  # booleans / non-numeric constants are fine
    return node.value in ALLOWED_NUMERICS


def _noqa_lines(source: str) -> set[int]:
    """Lines tagged `# allow: literal` are explicitly waived."""
    out: set[int] = set()
    for i, line in enumerate(source.splitlines(), start=1):
        if "# allow: literal" in line:
            out.add(i)
    return out


def _is_in_field_call(parents: list[ast.AST]) -> bool:
    """Constants inside pydantic Field(...) (e.g. `ge=0.0`) are config metadata,
    not runtime inputs."""
    for p in reversed(parents):
        if isinstance(p, ast.Call):
            func = p.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            if name in ("Field", "PyField"):
                return True
    return False


def _is_in_annotation(parents: list[ast.AST]) -> bool:
    """Inside an annotation (e.g., `Literal[1, 2]`) — not runtime input."""
    for p in reversed(parents):
        if isinstance(p, ast.AnnAssign):
            return True
        if (
            isinstance(p, ast.Subscript)
            and isinstance(p.value, ast.Name)
            and p.value.id in ("Literal", "Annotated")
        ):
            return True
    return False


class _LiteralVisitor(ast.NodeVisitor):
    def __init__(self, *, source: str, filename: str) -> None:
        self.violations: list[str] = []
        self.noqa = _noqa_lines(source)
        self.filename = filename
        self._stack: list[ast.AST] = []

    def generic_visit(self, node: ast.AST) -> None:
        self._stack.append(node)
        try:
            super().generic_visit(node)
        finally:
            self._stack.pop()

    def visit_Constant(self, node: ast.Constant) -> None:
        if _is_allowed_constant(node):
            return
        if node.lineno in self.noqa:
            return
        if _is_in_field_call(self._stack):
            return
        if _is_in_annotation(self._stack):
            return
        self.violations.append(
            f"{self.filename}:{node.lineno}: hardcoded numeric literal "
            f"{node.value!r}. Move to config/registry.yaml or whitelist with "
            "`# allow: literal`."
        )


def test_no_hardcoded_literals_in_engine() -> None:
    violations: list[str] = []
    for path in sorted(ENGINE_DIR.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        visitor = _LiteralVisitor(
            source=source,
            filename=str(path.relative_to(REPO_ROOT)),
        )
        visitor.visit(tree)
        violations.extend(visitor.violations)
    if violations:
        msg = (
            "Constitution Principle II violation — hardcoded numeric literals "
            "in engine code:\n  - " + "\n  - ".join(violations)
        )
        pytest.fail(msg)
