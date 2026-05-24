<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan:
[specs/002-fee-as-fare-pct/plan.md](specs/002-fee-as-fare-pct/plan.md)

Active feature (002 — diff against the 001 baseline):
- [spec.md](specs/002-fee-as-fare-pct/spec.md) — fee migrates from flat euros to % of fare
- [research.md](specs/002-fee-as-fare-pct/research.md) — migration decisions (rounding, loader error, stale-data detection)
- [data-model.md](specs/002-fee-as-fare-pct/data-model.md) — entity diff
- [contracts/](specs/002-fee-as-fare-pct/contracts/) — registry-schema-diff + ui-and-export-labels
- [quickstart.md](specs/002-fee-as-fare-pct/quickstart.md) — migration steps

Baseline feature (001 — full original spec; everything 002 doesn't change):
[specs/001-disruption-assistance-engine/](specs/001-disruption-assistance-engine/)

Governing principles (non-negotiable):
[.specify/memory/constitution.md](.specify/memory/constitution.md)

Run the app: `streamlit run src/ui/app.py` (after `python -m src.cli.generate_data`).
Run exports: `python -m src.cli.export --xlsx --html --no-llm --out exports/`.
Tests: `pytest tests/` (107 unit + integration + consistency + determinism tests).
Lint + type: `ruff check src/ tests/` and `mypy src/engine src/config src/data/schema.py`.
<!-- SPECKIT END -->
