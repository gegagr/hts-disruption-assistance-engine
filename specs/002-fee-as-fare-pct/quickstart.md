# Quickstart — Migrate to Fee as Percentage of Fare

**Audience**: a developer or finance analyst whose checkout is on the
001 fee-as-flat-cents model and wants to move to the 002 fee-as-fare-%
model.

## TL;DR (one-liner)

```bash
# 1. Edit config/registry.yaml (see below)
# 2. Regenerate the synthetic dataset
python -m src.cli.generate_data
# 3. Run tests
pytest
# 4. Launch the app — no further action needed
streamlit run src/ui/app.py
```

## Step 1 — Edit `config/registry.yaml`

**Before** (001):

```yaml
fee_level:
  control_cents:
    value: 1200
    origin: disclosed
    source: "Pricing committee 2025-11-04"
  test_cents:
    value: 900
    origin: disclosed
    source: "Pricing committee 2025-11-04"
```

**After** (002):

```yaml
fee_level:
  control_pct:
    value: 0.12
    origin: disclosed
    source: "Pricing committee 2025-11-04"
  test_pct:
    value: 0.10
    origin: disclosed
    source: "Pricing committee 2025-11-04"
```

If you forget to remove the old `*_cents` keys, the loader will fail
immediately with a clear error telling you exactly which key to
rename — no guesswork.

## Step 2 — Regenerate the dataset

The existing `data/generated/bookings.parquet` has per-booking fees
computed under the old flat-fee model. Under the new model, fees vary
with fare. Regenerate:

```bash
python -m src.cli.generate_data
```

You should see roughly the same booking count as before (~160k).
Cancellation count and ancillary count are unchanged (those don't
depend on fee). Revenue numbers will be different.

If you forget to regenerate, the app will detect the stale state on
first load and surface a banner with the regeneration command —
better that than render misleading numbers.

## Step 3 — Run the test suite

```bash
pytest
```

Expected: every test passes (same count as before the migration, plus
the new fee-derivation unit test). If a test asserting a specific
revenue number fails, check the assertion — the expected number under
the new model is `round(fee_pct × fare_cents)`, not the old flat fee.

## Step 4 — Launch the app

```bash
streamlit run src/ui/app.py
```

What you should see:

- **Performance**: same partner status colours, similar trailing
  charts. Revenue numbers shift because per-booking fees now scale
  with fare; loss ratios are lower (revenue is higher on long-haul
  routes where payouts dominate).
- **Variance**: per-partner gap unchanged (the realised vs priced
  *cancellation rate* doesn't depend on fee). Margin-impact figures
  shift because the average-fare component of the margin-impact
  formula now multiplies a variable fee.
- **A/B Test**: arm labels read `"Current fee (12% of fare)"` and
  `"Lower fee (10% of fare)"`. Verdict still names a winner; the
  comparison is now economically realistic (both arms' revenues
  scale with the same fare distribution).
- **Projection**: scenario headers read `"Standardise on the current
  fee (12% of fare)"` and `"Standardise on the lower fee (10% of
  fare)"`. 52-week totals reflect the new revenue derivation.

## Tweaking the fees

After the migration, changing the fees is one number edit:

```yaml
fee_level:
  control_pct:
    value: 0.13        # ← changed from 0.12
    origin: disclosed
    source: "Pricing committee 2026-04-01"
```

Then regenerate the dataset and refresh the app. The labels, every
view, the briefing, and every export reflect the new percentage. No
code edit, no rebuild.

## Rollback

If you need to revert to the 001 flat-fee model:

```bash
git checkout main -- config/registry.yaml src/config/schema.py src/config/loader.py \
                     src/data/generator.py src/engine/projection.py src/engine/dataset.py \
                     src/ui/ab_test.py src/ui/projection.py src/ui/app.py \
                     src/export/xlsx.py tests/
python -m src.cli.generate_data
```

(Or, if you've already merged 002, do a `git revert` of the merge
commit.)

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `RegistryLoadError: fee_level.control_cents was removed in feature 002...` | Registry file still has the legacy `*_cents` keys. | Edit `config/registry.yaml` per Step 1 above. |
| Banner: "Synthetic dataset is stale" | You edited the registry to the new shape but didn't regenerate. | Run `python -m src.cli.generate_data`. |
| Test fails: `assert booking.fee_cents == 1200` | Old hardcoded expectation. | Update to `round(fee_pct_for_arm × booking.fare_cents)`. |
| XLSX formula shows `#NAME?` | Old workbook references the removed `fee_level_control_cents` named range. | Re-export the workbook from the running app. |

## What didn't change

- The deterministic engine still produces bit-for-bit identical
  outputs across runs (SC-007 / SC-103).
- The 20+ cross-view consistency checks still pass with zero
  discrepancies.
- Origin tags survive end-to-end (UI, exports, briefing).
- Layer boundaries are intact.
- The synthetic-data generator's seed is unchanged; only the fee
  branch of the per-booking loop changed.
