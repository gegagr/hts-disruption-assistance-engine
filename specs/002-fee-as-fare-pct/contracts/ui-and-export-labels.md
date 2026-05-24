# Contract Diff — User-Facing Labels

**Replaces** the fee-related arm and scenario labels surfaced in
[specs/001-disruption-assistance-engine/contracts/export-layout.md](../../001-disruption-assistance-engine/contracts/export-layout.md)
and in the UI strings rendered by `src/ui/ab_test.py` and
`src/ui/projection.py`. Engine identifiers (`control`, `test`,
`pre_split`) remain unchanged per the original `pre_split` clarification.

---

## Source-of-truth derivation

All labels are derived **from the registry at render time** — no
hardcoded display strings of the form `"€12"` or `"€9"` survive.

```python
fee_control_pct = registry.fee_level.control_pct.value
fee_test_pct = registry.fee_level.test_pct.value
current_label = f"Current fee ({fee_control_pct * 100:.0f}% of fare)"
lower_label = f"Lower fee ({fee_test_pct * 100:.0f}% of fare)"
```

When the two percentages would render identically under `.0f`
formatting (e.g., `0.124` and `0.121` both → `"12"`), use one
decimal place: `f"{pct * 100:.1f}% of fare"`. Apply this rule
**consistently to both labels** so the contrast remains legible.

---

## A/B Test page (`src/ui/ab_test.py`)

| Surface | Before (001 + UI polish) | After (002) |
|---|---|---|
| Arm metric headers | `"Current fee (€12) — bookings since test launch"` | `"Current fee (12% of fare) — bookings since test launch"` |
| Verdict winner cards | `"Total contribution — Current fee (€12)"` | `"Total contribution — Current fee (12% of fare)"` |
| Metric table columns | `"Unadjusted — Current fee (€12)"`, `"Adjusted for partner mix — Current fee (€12)"` etc. | `"Unadjusted — Current fee (12% of fare)"`, `"Adjusted for partner mix — Current fee (12% of fare)"` etc. |
| Δ column | `"Δ adjusted (lower fee − current fee)"` | unchanged (already uses the symbolic labels) |
| Disagreements table headers | `"Contribution per booking — Current fee (€12)"` etc. | `"Contribution per booking — Current fee (12% of fare)"` etc. |
| Page caption | mentions split date, mix-adjustment method | unchanged |

---

## Projection page (`src/ui/projection.py`)

| Surface | Before | After |
|---|---|---|
| Scenario header | `"Standardise on the **current fee**"` | `"Standardise on the **current fee** (12% of fare)"` |
| Scenario header | `"Standardise on the **lower fee**"` | `"Standardise on the **lower fee** (10% of fare)"` |
| Monthly trajectory legend | `"Current fee (€12)"`, `"Lower fee (€9)"` | `"Current fee (12% of fare)"`, `"Lower fee (10% of fare)"` |
| Per-month table headers | `"Current fee (€12)"`, `"Lower fee (€9)"` | `"Current fee (12% of fare)"`, `"Lower fee (10% of fare)"` |
| Methodology note | "fee[s] from registry" | "fee[s] = fee_pct[s] × fare from registry" |

---

## Performance page (`src/ui/performance.py`)

The fee model doesn't surface directly in Performance labels (the
view aggregates revenue/cost without naming the arm). **No label
changes.** The P&L flow Sankey continues to render — its source
nodes are partners, not arms; its caption is unchanged.

---

## Variance page (`src/ui/variance.py`)

No fee labels. **No changes.**

---

## XLSX export (`src/export/xlsx.py`)

### Named ranges

| Before | After |
|---|---|
| `fee_level_control_cents` | `fee_level_control_pct` |
| `fee_level_test_cents` | `fee_level_test_pct` |

### ABTest sheet header text

Where the sheet header or any cell references the fee level by
display name, it MUST express it as a percentage. Per-sheet display
strings inherit the same `(pct * 100:.Nf)% of fare` derivation.

### Audit sheet

If any Audit-sheet formula previously referenced
`fee_level_control_cents` directly (as a check value), update the
reference to `fee_level_control_pct` and adjust the formula so the
arithmetic remains correct (e.g., if a check computed
`= fee_level_control_cents` to recover an arm's per-ancillary
revenue, it now computes `= fee_level_control_pct * fare` against a
sample fare value).

---

## HTML / PDF report (`src/export/html_report.py`)

The HTML template renders arm names from the same UI helpers (or
from a shared label helper exposed from `src.ui.components`). Any
embedded fee display string is derived from registry values; no
literal `"€12"` / `"€9"` survives in the template.

---

## Briefing

The briefing's evidence pack references partners and events, not fee
arms. No briefing strings change.

---

## Verification (testable)

- A UI test asserts that the A/B page's arm header contains
  `"of fare"`.
- The XLSX export test (`test_export_xlsx.py`) asserts
  `"fee_level_control_pct"` ∈ `wb.defined_names` and
  `"fee_level_control_cents"` ∉ `wb.defined_names`.
- The HTML export test parses the document and asserts no occurrence
  of the literal substring `"€12"` or `"€9"` in fee-arm contexts
  (a regex over the relevant section is acceptable).
