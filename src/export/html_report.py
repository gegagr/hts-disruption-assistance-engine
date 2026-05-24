"""Self-contained HTML report (FR-026).

Single-file Jinja2 render with inlined CSS and (where present) inlined
SVG charts. No external resources — verified by integration test.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment, select_autoescape
from markupsafe import Markup

from src.config.schema import Registry
from src.engine.ab_test import ABTestView
from src.engine.briefing import Briefing
from src.engine.consistency import ConsistencyReport
from src.engine.performance import PerformanceView
from src.engine.projection import ProjectionView
from src.engine.variance import VarianceView
from src.ui.components import (
    APP_SUBTITLE,
    APP_TITLE,
    format_date,
    format_week_commencing,
)

ORIGIN_COLOURS = {
    "disclosed": "#cce5ff",
    "observed": "#d4edda",
    "measured-from-data": "#e2e3e5",
    "assumed": "#fff3cd",
}
ORIGIN_LETTERS = {
    "disclosed": "D",
    "observed": "O",
    "measured-from-data": "M",
    "assumed": "A",
}


TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ app_title }} — {{ as_of_wc }}</title>
<style>
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       margin: 0; padding: 24px; color: #222; max-width: 1200px; margin-inline: auto; }
h1 { font-size: 1.6em; margin-bottom: 4px; }
h2 { font-size: 1.2em; margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
h3 { font-size: 1.0em; margin-top: 16px; }
.meta { color: #666; font-size: 0.9em; }
.banner { padding: 12px; border-radius: 6px; margin: 12px 0; }
.banner.fail { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
.banner.pass { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
/* Readable badges on both light AND dark backgrounds: dark text on a coloured chip. */
.mode-badge { font-size: 0.85em; padding: 2px 10px; border-radius: 8px;
              vertical-align: middle; margin-left: 8px; font-weight: 600;
              white-space: nowrap; }
.mode-llm { background: #9DD8E2; color: #0B2A30; }
.mode-template { background: #F2C56B; color: #3A2A0A; }
.origin { font-size: 0.7em; padding: 1px 5px; border-radius: 6px;
          vertical-align: super; margin-left: 4px; color: #222; }
/* One coherent table treatment everywhere — dark header, light body. */
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 0.92em; }
th { background: #131519; color: #ECEDEE; font-weight: 600;
     padding: 10px 12px; text-align: left; border-bottom: 1px solid #2A2E33; }
th.num { text-align: right; }
th .subtitle { display: block; font-weight: 400; color: #9BA1A8;
               font-size: 0.85em; margin-top: 2px; }
td { padding: 8px 12px; border-bottom: 1px solid rgba(0,0,0,0.08);
     vertical-align: top; }
td.num { text-align: right;
         font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace;
         font-variant-numeric: tabular-nums; }
td .subline { color: #888; font-size: 0.8em; margin-top: 2px; }
td .primary { font-weight: 600; }
.figure { display: inline-block; }
.bullet { margin: 4px 0 4px 16px; }
.note { color: #555; font-size: 0.85em; font-style: italic; }
.scenarios { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.section { margin-bottom: 32px; }
.ab-table { table-layout: fixed; }
/* One coherent pill treatment — mint-tinted, readable. */
.scenario-pill { background: #103E2E; color: #7FE3B2; padding: 2px 10px;
                 border-radius: 10px; font-weight: 600; white-space: nowrap;
                 display: inline-block; }
.scenario-pill.lower { background: #3A2410; color: #F5C896; }
.scenario-pill.tie { background: #2A2A2A; color: #C7CCD3; }
.verdict { background: #F4F6F8; border-left: 4px solid #9DD8E2; padding: 12px 16px;
           margin: 8px 0; border-radius: 4px; }
</style>
</head>
<body>

<h1>{{ app_title }}</h1>
<p class="meta">{{ app_subtitle }}</p>
<p class="meta">As of {{ as_of_wc }} · generated {{ generated_at }}</p>

{% if not consistency.passed %}
<div class="banner fail">
  <strong>Consistency check FAILED</strong> — {{ consistency.discrepancies|length }} discrepancies.
  Investigate before trusting any single tile.
</div>
{% else %}
<div class="banner pass">
  Consistency check passed ({{ consistency.checks|length }} cross-view checks).
</div>
{% endif %}

<section class="section" id="briefing">
  <h2>Briefing
    <span class="mode-badge mode-{{ briefing.mode }}">{{ briefing_badge }}</span>
  </h2>
  {% for line in briefing_lines %}
    <p>{{ line }}</p>
  {% endfor %}
</section>

<section class="section" id="performance">
  <h2>Performance — current week</h2>
  <table>
    <thead><tr>
      <th>Partner</th><th>Status</th>
      <th class="num">Revenue</th><th class="num">Payouts</th>
      <th class="num">Cost of service</th><th class="num">Contribution</th>
      <th class="num">Attach</th><th class="num">Loss ratio</th><th class="num">Gross margin</th>
      <th class="num">Margin Δ floor (bps)</th>
    </tr></thead>
    <tbody>
    {% for status in performance.partners %}
    <tr>
      <td>{{ status.display_name }}</td>
      <td>{{ status.status }}</td>
      <td class="num"><span class="figure" data-figure-id="perf.{{ status.partner_id }}.revenue">{{ fmt_eur(status.current.revenue_cents) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="perf.{{ status.partner_id }}.payouts">{{ fmt_eur(status.current.payouts_cents) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="perf.{{ status.partner_id }}.cos">{{ fmt_eur(status.current.cost_of_service_cents) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="perf.{{ status.partner_id }}.contribution">{{ fmt_eur(status.current.contribution_cents) }}</span></td>
      <td class="num">{{ fmt_pct(status.current.attach_rate) }}</td>
      <td class="num">{{ fmt_pct(status.current.loss_ratio) }}</td>
      <td class="num">{{ fmt_pct(status.current.gross_margin_pct) }}</td>
      <td class="num">{{ status.margin_distance_from_floor_bps|int }}</td>
    </tr>
    {% endfor %}
    <tr style="font-weight:600;">
      <td>{{ performance.blended.display_name }}</td>
      <td>{{ performance.blended.status }}</td>
      <td class="num"><span class="figure" data-figure-id="perf.blended.revenue">{{ fmt_eur(performance.blended.current.revenue_cents) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="perf.blended.payouts">{{ fmt_eur(performance.blended.current.payouts_cents) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="perf.blended.cos">{{ fmt_eur(performance.blended.current.cost_of_service_cents) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="perf.blended.contribution">{{ fmt_eur(performance.blended.current.contribution_cents) }}</span></td>
      <td class="num">{{ fmt_pct(performance.blended.current.attach_rate) }}</td>
      <td class="num">{{ fmt_pct(performance.blended.current.loss_ratio) }}</td>
      <td class="num">{{ fmt_pct(performance.blended.current.gross_margin_pct) }}</td>
      <td class="num">{{ performance.blended.margin_distance_from_floor_bps|int }}</td>
    </tr>
    </tbody>
  </table>
</section>

<section class="section" id="variance">
  <h2>Variance — priced vs realised (trailing {{ variance.trailing_window_weeks }} weeks)</h2>
  <table>
    <thead><tr>
      <th>Partner</th>
      <th class="num">Priced (bps)<span class="origin" style="background:{{ origin_colour('disclosed') }}">{{ origin_letter('disclosed') }}</span></th>
      <th class="num">Realised (bps)<span class="origin" style="background:{{ origin_colour('measured-from-data') }}">{{ origin_letter('measured-from-data') }}</span></th>
      <th class="num">Gap (bps)</th>
      <th class="num">Margin impact</th>
      <th>Hidden in blended view</th>
    </tr></thead>
    <tbody>
    {% for r in variance.rows %}
    <tr>
      <td>{{ variance_partner_label(r) }}</td>
      <td class="num"><span class="figure" data-figure-id="var.{{ r.partner_id }}.priced">{{ r.priced_cancel_rate_bps|int }}</span></td>
      <td class="num"><span class="figure" data-figure-id="var.{{ r.partner_id }}.realised">{{ r.realised_cancel_rate_bps|int if r.realised_cancel_rate_bps is not none else "—" }}</span></td>
      <td class="num"><span class="figure" data-figure-id="var.{{ r.partner_id }}.gap">{{ r.gap_bps|int if r.gap_bps is not none else "—" }}</span></td>
      <td class="num"><span class="figure" data-figure-id="var.{{ r.partner_id }}.impact">{{ fmt_eur(r.margin_impact_cents) }}</span></td>
      <td>{{ "yes" if r.hidden_by_blend else "" }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
</section>

<section class="section" id="ab-test">
  <h2>A/B Test — Current fee vs Lower fee</h2>
  <p class="note">
    Test launched on {{ ab_launched }} ·
    bookings since launch: Current fee {{ "{:,}".format(ab.arm_sizes['control']) }} ·
    Lower fee {{ "{:,}".format(ab.arm_sizes['test']) }} ·
    mix-adjustment: {{ ab.mix_control_method }}<span class="origin" style="background:{{ origin_colour(ab.reference_mix_origin) }}">{{ origin_letter(ab.reference_mix_origin) }}</span>
  </p>
  <table class="ab-table">
    <thead><tr>
      <th>Metric</th>
      <th class="num">Current fee<span class="subtitle">{{ current_pct }} of fare</span></th>
      <th class="num">Lower fee<span class="subtitle">{{ lower_pct }} of fare</span></th>
      <th>Winner</th>
    </tr></thead>
    <tbody>
    {% for m in ab.metrics %}
    <tr>
      <td>{{ metric_label(m.metric) }}</td>
      <td class="num">
        <div class="primary"><span class="figure" data-figure-id="ab.{{ m.metric }}.strat.control">{{ fmt_metric(m.metric, m.stratified['control']) }}</span></div>
        <div class="subline">unadjusted: <span class="figure" data-figure-id="ab.{{ m.metric }}.naive.control">{{ fmt_metric(m.metric, m.naive['control']) }}</span></div>
      </td>
      <td class="num">
        <div class="primary"><span class="figure" data-figure-id="ab.{{ m.metric }}.strat.test">{{ fmt_metric(m.metric, m.stratified['test']) }}</span></div>
        <div class="subline">unadjusted: <span class="figure" data-figure-id="ab.{{ m.metric }}.naive.test">{{ fmt_metric(m.metric, m.naive['test']) }}</span></div>
      </td>
      <td>{{ scenario_pill(m.winning_arm) }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  <h3>Verdict</h3>
  <div class="verdict">
    <p>Adjusted for partner mix, contribution per booking favours {{ scenario_pill(ab.verdict.winner_on_contribution_per_booking) }}.
       Total contribution favours {{ scenario_pill(ab.verdict.winner_on_total_contribution) }}.</p>
    <p>Total contribution — Current fee: <span class="figure" data-figure-id="ab.total.control">{{ fmt_eur(ab.verdict.total_contribution_cents['control']) }}</span>
       · Lower fee: <span class="figure" data-figure-id="ab.total.test">{{ fmt_eur(ab.verdict.total_contribution_cents['test']) }}</span></p>
    <p class="note">{{ compose_tradeoff(ab) }}</p>
  </div>
</section>

<section class="section" id="projection">
  <h2>Projection — {{ projection.weeks_forward }} weeks forward, side-by-side</h2>
  <div class="scenarios">
  {% for scenario in projection.scenarios %}
    {% set t = projection.totals[scenario] %}
    <div>
      <h3>{{ pretty_scenario(scenario) }}</h3>
      <table>
        <tr><th>Revenue (52w)</th><td class="num"><span class="figure" data-figure-id="proj.{{ scenario }}.revenue">{{ fmt_eur(t.revenue_cents) }}</span></td></tr>
        <tr><th>Payouts (52w)</th><td class="num"><span class="figure" data-figure-id="proj.{{ scenario }}.payouts">{{ fmt_eur(t.payouts_cents) }}</span></td></tr>
        <tr><th>Cost of service</th><td class="num"><span class="figure" data-figure-id="proj.{{ scenario }}.cos">{{ fmt_eur(t.cost_of_service_cents) }}</span></td></tr>
        <tr><th>Contribution</th><td class="num"><span class="figure" data-figure-id="proj.{{ scenario }}.contribution">{{ fmt_eur(t.contribution_cents) }}</span></td></tr>
        <tr><th>Volume (52w)</th><td class="num">{{ "{:,}".format(t.volume) }}</td></tr>
      </table>
    </div>
  {% endfor %}
  </div>
  <h3>Drivers</h3>
  <table>
    <thead><tr><th>Driver</th><th class="num">Value</th><th>Origin</th><th>Formula</th></tr></thead>
    <tbody>
    {% for d in projection.drivers %}
    <tr>
      <td>{{ driver_label(d.name) }}</td>
      <td class="num">{{ fmt_driver(d.name, d.value) }}<span class="origin" style="background:{{ origin_colour(d.origin) }}">{{ origin_letter(d.origin) }}</span></td>
      <td>{{ d.origin }}</td>
      <td>{{ d.formula }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  <p class="note">{{ projection.methodology_note }}</p>
</section>

<footer class="meta" style="margin-top:48px; border-top: 1px solid #ddd; padding-top: 12px;">
  <p>Origin legend:
    {% for origin, letter in origin_letters.items() %}
    <span class="origin" style="background:{{ origin_colours[origin] }}">{{ letter }}</span> {{ origin }}
    {% if not loop.last %}·{% endif %}
    {% endfor %}
  </p>
</footer>

</body>
</html>
"""


def _fmt_eur(cents: int | None) -> str:
    if cents is None:
        return "—"
    sign = "-" if cents < 0 else ""
    return f"{sign}€{abs(cents) // 100:,}.{abs(cents) % 100:02d}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _fmt_metric(metric: str, value: float) -> str:
    if metric == "contribution_per_booking_cents":
        return _fmt_eur(round(value))
    return f"{value * 100:.2f}%"


def _fmt_driver(name: str, value: float) -> str:
    if "rate" in name or "ratio" in name or ("pct" in name and "cents" not in name):
        return f"{value * 100:.2f}%"
    if "cents" in name and "stratified" not in name:
        return _fmt_eur(round(value))
    if "stratified" in name and "contribution_per_booking" in name:
        return _fmt_eur(round(value))
    return f"{value:,.4f}"


def _pretty_scenario(s: str, current_label: str, lower_label: str) -> str:
    return {
        "standardise_on_control": f"Standardise on {current_label}",
        "standardise_on_test": f"Standardise on {lower_label}",
    }.get(s, s)


def _fmt_arm_pct(pct: float, other: float) -> str:
    """Format a fee percentage for an arm label; use 1dp if both arms collide at 0dp."""
    if round(pct * 100) == round(other * 100):
        return f"{pct * 100:.1f}%"
    return f"{pct * 100:.0f}%"


_METRIC_LABELS = {
    "attach_rate": "Attach rate",
    "loss_ratio": "Loss ratio",
    "gross_margin_pct": "Gross margin",
    "contribution_per_booking_cents": "Contribution per booking",
}


def _metric_label(metric: str) -> str:
    return _METRIC_LABELS.get(metric, metric)


_SCENARIO_NAMES = {"control": "Current fee", "test": "Lower fee", "tie": "Tie"}


def _scenario_name(winner: str) -> str:
    return _SCENARIO_NAMES.get(winner, winner)


def _scenario_pill(winner: str) -> Markup:
    """Render a short non-wrapping pill for a winner arm name."""
    name = _scenario_name(winner)
    cls = {"control": "current", "test": "lower", "tie": "tie"}.get(winner, "")
    classes = f"scenario-pill{(' ' + cls) if cls else ''}"
    return Markup(f'<span class="{classes}">{name}</span>')


def _variance_partner_label(row: Any) -> Markup:
    """Bold the blended row and rename it to plain language. Per-partner rows
    keep their display_name verbatim from the engine."""
    from src.engine.aggregates import BLENDED_PARTNER

    if row.partner_id == BLENDED_PARTNER:
        return Markup("<strong>Blended (all partners)</strong>")
    return Markup(escape(row.display_name))


_DRIVER_LABELS = {
    "blended_attach_rate": "Attach rate (blended)",
    "blended_loss_ratio": "Loss ratio (blended)",
    "blended_avg_fare_cents": "Average fare",
    "blended_priced_cancel_rate": "Priced cancel rate (blended)",
    "blended_realised_cancel_rate": "Realised cancel rate (blended)",
    "weekly_volume": "Weekly volume",
    "trend_factor": "Trend factor",
    "coverage_pct": "Coverage %",
    "payment_processing_pct": "Payment processing %",
    "servicing_cost_per_unit_cents": "Servicing cost per ancillary",
    "stratified_contribution_per_booking_control": (
        "Contribution per booking — Current fee (mix-adjusted)"
    ),
    "stratified_contribution_per_booking_test": (
        "Contribution per booking — Lower fee (mix-adjusted)"
    ),
}


def _driver_label(name: str) -> str:
    if name in _DRIVER_LABELS:
        return _DRIVER_LABELS[name]
    label = name.replace("_", " ")
    label = label.replace("stratified", "(mix-adjusted)")
    label = label.replace(" control", " — Current fee")
    label = label.replace(" test", " — Lower fee")
    return label[:1].upper() + label[1:]


def _compose_tradeoff(ab: Any) -> str:
    """Plain-language trade-off line composed from structured fields.

    Never surfaces the engine's raw "control arm / test arm" sentence.
    """
    attach = next((m for m in ab.metrics if m.metric == "attach_rate"), None)
    cpb = next(
        (m for m in ab.metrics if m.metric == "contribution_per_booking_cents"),
        None,
    )
    if attach is None or cpb is None:
        return ""
    higher_attach = "test" if attach.stratified["test"] > attach.stratified["control"] else "control"
    higher_cpb = "test" if cpb.stratified["test"] > cpb.stratified["control"] else "control"
    if higher_attach == higher_cpb:
        return (
            f"{_scenario_name(higher_cpb)} wins on both attach rate and "
            "contribution per booking — no trade-off."
        )
    ctl_eur = ab.verdict.total_contribution_cents["control"] / 100
    tst_eur = ab.verdict.total_contribution_cents["test"] / 100
    return (
        f"Volume vs margin: {_scenario_name(higher_attach)} wins on attach rate, "
        f"{_scenario_name(higher_cpb)} wins on contribution per booking. "
        f"Total contribution — Current fee €{ctl_eur:,.0f} vs Lower fee "
        f"€{tst_eur:,.0f}."
    )


def write_report(
    *,
    performance: PerformanceView,
    variance: VarianceView,
    ab_test: ABTestView,
    projection: ProjectionView,
    briefing: Briefing,
    consistency: ConsistencyReport,
    registry: Registry,
    path: str | Path,
) -> Path:
    ctl_pct = registry.fee_level.control_pct.value
    tst_pct = registry.fee_level.test_pct.value
    current_pct = _fmt_arm_pct(ctl_pct, tst_pct)
    lower_pct = _fmt_arm_pct(tst_pct, ctl_pct)
    # Projection section still uses the old long labels for scenario titles
    current_label = f"Current fee ({current_pct} of fare)"
    lower_label = f"Lower fee ({lower_pct} of fare)"

    env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
    env.globals["fmt_eur"] = _fmt_eur
    env.globals["fmt_pct"] = _fmt_pct
    env.globals["fmt_metric"] = _fmt_metric
    env.globals["fmt_driver"] = _fmt_driver
    env.globals["metric_label"] = _metric_label
    env.globals["scenario_pill"] = _scenario_pill
    env.globals["variance_partner_label"] = _variance_partner_label
    env.globals["driver_label"] = _driver_label
    env.globals["compose_tradeoff"] = _compose_tradeoff
    env.globals["pretty_scenario"] = lambda s: _pretty_scenario(
        s, current_label, lower_label
    )
    env.globals["origin_colour"] = lambda o: ORIGIN_COLOURS.get(o, "#eee")
    env.globals["origin_letter"] = lambda o: ORIGIN_LETTERS.get(o, "?")
    env.globals["origin_colours"] = ORIGIN_COLOURS
    env.globals["origin_letters"] = ORIGIN_LETTERS

    briefing_lines = briefing.rendered_text.split("\n")
    briefing_badge = _briefing_badge_text(briefing.mode, briefing.provider)

    start_date = registry.dataset.start_date.value
    html = env.from_string(TEMPLATE).render(
        app_title=APP_TITLE,
        app_subtitle=APP_SUBTITLE,
        as_of_wc=format_week_commencing(performance.as_of_week, start_date),
        ab_launched=format_date(ab_test.split_date),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        consistency=consistency,
        briefing=briefing,
        briefing_lines=briefing_lines,
        briefing_badge=briefing_badge,
        performance=performance,
        variance=variance,
        ab=ab_test,
        projection=projection,
        current_pct=current_pct,
        lower_pct=lower_pct,
    )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _briefing_badge_text(mode: str, provider: str | None) -> str:
    """Mirrors src/ui/components.mode_badge — names the LLM provider in
    LLM mode so a reader knows the source."""
    if mode == "llm":
        return {"anthropic": "Claude", "openrouter": "Gemini 2.0 Flash"}.get(
            provider or "", "LLM"
        )
    return "deterministic fallback"
