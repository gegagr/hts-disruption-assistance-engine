# Quickstart — Disruption Assistance Performance Engine

**Audience**: a developer or finance analyst pulling the repo for the first
time. This is the shortest path from clone to a working tool.

## Prerequisites

- Python 3.11.
- macOS or Linux (WeasyPrint needs `cairo`, `pango`, `gdk-pixbuf`).
  - macOS: `brew install cairo pango gdk-pixbuf libffi`
  - Debian/Ubuntu: `sudo apt install libcairo2 libpango1.0-0 libgdk-pixbuf2.0-0 libffi-dev`
- `ANTHROPIC_API_KEY` in the environment **only** if you want the
  LLM-generated briefing. Without it, the tool runs in `template
  (fallback)` mode.

## One-time setup

```bash
git clone <repo>
cd hts-see-finance-engine
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]            # installs runtime + dev dependencies
```

## Five-minute happy path

```bash
# 1. Generate the synthetic dataset (deterministic, seeded from registry)
python -m src.cli.generate_data

# 2. Launch the Streamlit app
streamlit run src/ui/app.py

# 3. In the browser, open http://localhost:8501
#    - Sidebar → set "as-of week" (defaults to last week of dataset)
#    - Sidebar → toggle "LLM briefing" off if you want deterministic output
#    - Tabs: Performance | Variance | A/B Test | Projection
```

## Export artefacts (CLI)

```bash
# Without browser, produce all three exports for the last week of data
python -m src.cli.export --xlsx --html --pdf --out exports/

# Reproducible export (no LLM call; template-rendered briefing)
python -m src.cli.export --xlsx --html --pdf --no-llm --out exports/

# Specific as-of week
python -m src.cli.export --as-of-week 21 --xlsx --html --pdf
```

Exit code `2` indicates the consistency check failed and no artefacts were
written. Investigate `tests/consistency/` and the engine module that
produced the disagreeing figure.

## Run the tests

```bash
pytest                           # all suites
pytest tests/unit                # fastest: schemas + math
pytest tests/integration         # view-level end-to-end on a fixed dataset
pytest tests/consistency         # cross-view reconciliation (FR-027)
pytest -k determinism            # SC-007: same input → same output, twice
```

## Edit an assumption

Every input the engine reads lives in `config/registry.yaml`. Edit the
file (don't put a literal in code) and rerun.

Example: tighten the margin floor from 1500 bps to 1700 bps.

```yaml
margin:
  floor_bps: { value: 1700, origin: assumed }    # was 1500
```

Restart the Streamlit process (or click "rerun" in the sidebar); the
Performance briefing will reflect the tighter floor on next render.

## Reading an export

- Open `exports/DA_Engine_<week>.xlsx`.
- Go to `Assumptions`. Every yellow row is an `assumed` value — these
  are the cells most worth challenging.
- Try editing `coverage_pct` from 0.85 to 0.90. The `Performance` and
  `Variance` sheets recompute live; the `Projection` sheet updates the
  per-week and total cells.
- The `Audit` sheet re-derives the headline current-week contribution
  from first principles — useful for a hand check.
- The mode badge on the `Briefing` sheet tells you whether the prose was
  written by Claude or by the deterministic template.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ValidationError: origin=disclosed requires source` | A registry entry tagged `disclosed` lost its `source:` field. | Add the citation back. |
| Streamlit shows "Consistency check failed" banner | An engine module produced a figure inconsistent with another view. | Run `pytest tests/consistency -v`; the failing check names the disagreeing values. |
| Briefing always says `template (fallback)` | `ANTHROPIC_API_KEY` unset, SDK missing, or `briefing.llm_enabled: false` in registry. | Set the env var; check `pip show anthropic`; flip the registry flag. |
| `weasyprint` ImportError on macOS | Missing system libs. | `brew install cairo pango gdk-pixbuf libffi`. |
| `pandas.errors.EmptyDataError` from generator | Edited registry to set a partner's weekly volume to 0. | Set the partner's `activation_week` instead of zero volume. |
| Different numbers across two runs | Some code introduced wallclock or unseeded random behaviour. | `pytest -k determinism` will identify it. |

## What's intentionally not here

Per the spec's `Future` section and Constitution Principle V, the
following are out of scope and should NOT be added without an amendment
to the constitution and the spec:

- Live data ingestion.
- More than one product or region.
- Monte Carlo on the projection.
- Statistical-significance testing on the A/B view.
- Per-partner cost-of-service overrides.
- Authentication / multi-user features.

If you find yourself reaching for one of these, stop and open an
amendment first.
