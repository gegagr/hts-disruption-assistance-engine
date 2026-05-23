# Contract — Export Layout (XLSX, HTML, PDF)

**Purpose**: define the structure of the three export artefacts so a
finance-literate non-coder can interrogate the numbers (Constitution
Principle VI), and so the HTML and PDF remain content-equivalent (FR-026).

## XLSX workbook

Filename: `DA_Engine_<as_of_week>.xlsx` (e.g., `DA_Engine_2026W21.xlsx`).
Producer: `src.export.xlsx.write_workbook(views, registry, briefing, path)`.

### Sheets (in tab order)

| # | Sheet | Purpose |
|---|---|---|
| 1 | `README` | One-page legend: origin colour key, named-range index, how to edit assumptions. |
| 2 | `Assumptions` | The registry, one row per leaf entry, with value, origin, source, notes. Every entry has a defined name (workbook-scoped). |
| 3 | `WeeklyAggregates` | Long-form table: one row per (partner_id, iso_week, route_type, ab_arm). All raw numeric facts and the derived metrics. |
| 4 | `Performance` | Current-week partner status table + trailing-window mini-tables. All derived cells are formulas referencing `Assumptions` and `WeeklyAggregates`. |
| 5 | `Variance` | Per-partner priced-vs-actual rows + route-level drilldown. |
| 6 | `ABTest` | Two-arm comparison: naive and stratified, per metric. Includes the partner-arm-disagreement table. |
| 7 | `Projection` | 52-week × 2-scenario weekly table + totals. Drivers panel at top with named ranges. |
| 8 | `Briefing` | Mode badge (`LLM` / `template (fallback)`); narrative text; evidence pack table (id, value, origin). |
| 9 | `Consistency` | The `ConsistencyReport`: every cross-view check and pass/fail. |
| 10 | `Audit` | Worked-example cells that re-derive headline figures from first principles (visual cross-check). |

### Named ranges

Each registry leaf is exposed as a workbook-scoped defined name (Excel
`Name Manager`), pointing to the value cell on the `Assumptions` sheet.
Naming pattern:

```text
coverage_pct
payment_processing_pct
servicing_cost_per_unit_cents
fee_level_control_cents
fee_level_test_cents
metrics_trailing_window_weeks
margin_floor_bps
margin_approaching_floor_buffer_bps
classification_material_gap_bps
classification_persistence_weeks
projection_weeks_forward
projection_trend_factor
partner_bank_portal_priced_cancel_rate
partner_regional_carrier_a_priced_cancel_rate
partner_budget_carrier_priced_cancel_rate
ab_split_date
ab_fee_control_cents
ab_fee_test_cents
```

Derived sheets reference these names exclusively in formulas.

### Formula examples

On `Performance`, cell for partner `bank_portal` current-week revenue:

```excel
=SUMIFS(WeeklyAggregates!K:K,                              # revenue_cents column
        WeeklyAggregates!A:A, "bank_portal",
        WeeklyAggregates!B:B, current_week,
        WeeklyAggregates!C:C, "<all>",                     # route_type aggregated
        WeeklyAggregates!D:D, "all")                       # ab_arm aggregated
```

On `Projection`, weekly revenue for scenario `standardise_on_test`:

```excel
=projection_weeks_forward * 0  +   # unused, kept for shape symmetry
 [@volume] * [@attach_rate] * ab_fee_test_cents
```

Every derived cell MUST contain a formula, not a constant. Verified by a
test that opens the workbook with `openpyxl(load_workbook(...,
data_only=False))` and walks each non-input sheet asserting `cell.value`
starts with `=` for derived cells.

### Origin colour key

On `Assumptions`, the `origin` column is colour-coded:
- `disclosed` — light blue
- `observed` — light green
- `measured-from-data` — light grey
- `assumed` — light yellow

The same key is rendered on `README` and on the HTML report.

---

## HTML report

Filename: `DA_Engine_<as_of_week>.html`.
Producer: `src.export.html_report.write_report(views, briefing, path)`.

### Structure

Single self-contained file. CSS inline. Charts inline as SVG. No external
fonts (system stack). One top-level `<header>`, then four `<section>`s
matching the views, then briefing, then a consistency banner.

```html
<header>
  <h1>Disruption Assistance — Performance Report</h1>
  <p>As of week <span data-figure="as_of_week">…</span></p>
  <p>Generated <time datetime="…">…</time></p>
</header>

<section id="briefing">
  <h2>Briefing
    <span class="mode-badge mode-llm | mode-template">LLM | template (fallback)</span>
  </h2>
  <p class="headline">…</p>
  <ul class="partner-callouts">…</ul>
  <ul class="event-callouts">…</ul>
  <ul class="floor-callouts">…</ul>
</section>

<section id="performance">…</section>
<section id="variance">…</section>
<section id="ab-test">…</section>
<section id="projection">…</section>

<section id="consistency" class="consistency-pass | consistency-fail">…</section>
<section id="assumptions">…</section>   <!-- full registry table -->
```

### Origin tags

Every figure in every table is wrapped:

```html
<span class="figure" data-figure-id="…">
  €12,345.67
  <sup class="origin origin-disclosed" title="DA Product T&Cs §3.2">D</sup>
</span>
```

Letter codes: `M` measured-from-data, `D` disclosed, `O` observed, `A`
assumed. Hovering reveals the citation.

### Self-containment test

Integration test loads the produced HTML with `BeautifulSoup` and asserts:
- No `<link rel="stylesheet" href="…">` with external href.
- No `<img src>` referencing an http(s) URL.
- No `<script src>` references.
- Origin tags are present on every figure.

---

## PDF

Filename: `DA_Engine_<as_of_week>.pdf`.
Producer: `src.export.pdf.write_pdf(html_path, pdf_path)` — WeasyPrint
converts the same HTML.

The PDF MUST be content-equivalent (FR-026): same figures, same briefing
text, same origin tags. The only differences allowed are layout-level
(page breaks, repeating table headers, print-friendly margins).

### Verification

Integration test:
1. Renders the HTML.
2. Converts via WeasyPrint.
3. Extracts text from the PDF (`pdfplumber`).
4. Asserts every numeric figure in the HTML (`data-figure-id` spans) is
   present in the extracted PDF text.
5. Asserts the mode badge text (`LLM` or `template (fallback)`) appears
   in both.

---

## CLI surface

```text
python -m src.cli.export --as-of-week 21 --xlsx --html --pdf --out exports/
```

Flags:
- `--xlsx` / `--html` / `--pdf` are individually optional; at least one required.
- `--as-of-week N` defaults to the last week present in the dataset.
- `--out DIR` defaults to `./exports/`.
- `--no-llm` forces template-mode briefing for reproducible exports in CI.

Exit codes:
- `0` — success, consistency check passed.
- `2` — consistency check failed (artefacts not written; error to stderr).
- `3` — registry validation failed.
