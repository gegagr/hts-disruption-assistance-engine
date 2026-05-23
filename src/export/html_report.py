"""Self-contained HTML report (FR-026).

Single-file Jinja2 render with inlined CSS and (where present) inlined
SVG charts. No external resources — verified by integration test.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, BaseLoader, select_autoescape

from src.engine.ab_test import ABTestView
from src.engine.briefing import Briefing
from src.engine.consistency import ConsistencyReport
from src.engine.performance import PerformanceView
from src.engine.projection import ProjectionView
from src.engine.variance import VarianceView

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
<title>HTS DA Performance — week {{ as_of_week }}</title>
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
.mode-badge { font-size: 0.8em; padding: 2px 8px; border-radius: 8px;
              vertical-align: middle; margin-left: 8px; font-weight: 600; }
.mode-llm { background: #d1ecf1; }
.mode-template { background: #fff3cd; }
.origin { font-size: 0.7em; padding: 1px 5px; border-radius: 6px;
          vertical-align: super; margin-left: 4px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 0.9em; }
th, td { border: 1px solid #ccc; padding: 6px 8px; text-align: left; }
th { background: #f0f0f0; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.figure { display: inline-block; }
.bullet { margin: 4px 0 4px 16px; }
.note { color: #555; font-size: 0.85em; font-style: italic; }
.scenarios { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.section { margin-bottom: 32px; }
</style>
</head>
<body>

<h1>HTS Disruption Assistance — Performance Report</h1>
<p class="meta">As of ISO week {{ as_of_week }} · generated {{ generated_at }}</p>

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
    <span class="mode-badge mode-{{ briefing.mode }}">
      {{ briefing.mode if briefing.mode == "llm" else "template (fallback)" }}
    </span>
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
      <th>Hidden by blend?</th>
    </tr></thead>
    <tbody>
    {% for r in variance.rows %}
    <tr>
      <td>{{ r.display_name }}</td>
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
  <h2>A/B Test — control vs test fee</h2>
  <p class="note">
    Arm sizes (post-split bookings): control {{ "{:,}".format(ab.arm_sizes['control']) }} ·
    test {{ "{:,}".format(ab.arm_sizes['test']) }} ·
    mix-control method: {{ ab.mix_control_method }}<span class="origin" style="background:{{ origin_colour(ab.reference_mix_origin) }}">{{ origin_letter(ab.reference_mix_origin) }}</span>
  </p>
  <table>
    <thead><tr>
      <th>Metric</th>
      <th class="num">Naive — control</th>
      <th class="num">Naive — test</th>
      <th class="num">Stratified — control</th>
      <th class="num">Stratified — test</th>
      <th>Winner</th>
    </tr></thead>
    <tbody>
    {% for m in ab.metrics %}
    <tr>
      <td>{{ m.metric }}</td>
      <td class="num"><span class="figure" data-figure-id="ab.{{ m.metric }}.naive.control">{{ fmt_metric(m.metric, m.naive['control']) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="ab.{{ m.metric }}.naive.test">{{ fmt_metric(m.metric, m.naive['test']) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="ab.{{ m.metric }}.strat.control">{{ fmt_metric(m.metric, m.stratified['control']) }}</span></td>
      <td class="num"><span class="figure" data-figure-id="ab.{{ m.metric }}.strat.test">{{ fmt_metric(m.metric, m.stratified['test']) }}</span></td>
      <td>{{ m.winning_arm }}</td>
    </tr>
    {% endfor %}
    </tbody>
  </table>
  <h3>Verdict</h3>
  <p><strong>Winner on contribution per booking</strong>: {{ ab.verdict.winner_on_contribution_per_booking }} ·
     <strong>winner on total contribution</strong>: {{ ab.verdict.winner_on_total_contribution }}</p>
  <p>Total contribution — control: <span class="figure" data-figure-id="ab.total.control">{{ fmt_eur(ab.verdict.total_contribution_cents['control']) }}</span>
     · test: <span class="figure" data-figure-id="ab.total.test">{{ fmt_eur(ab.verdict.total_contribution_cents['test']) }}</span></p>
  <p class="note">{{ ab.verdict.tradeoff_summary }}</p>
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
    <thead><tr><th>Driver</th><th>Value</th><th>Origin</th><th>Formula</th></tr></thead>
    <tbody>
    {% for d in projection.drivers %}
    <tr>
      <td>{{ d.name }}</td>
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
        return _fmt_eur(int(round(value)))
    return f"{value * 100:.2f}%"


def _fmt_driver(name: str, value: float) -> str:
    if "rate" in name or "ratio" in name or ("pct" in name and "cents" not in name):
        return f"{value * 100:.2f}%"
    if "cents" in name and "stratified" not in name:
        return _fmt_eur(int(round(value)))
    if "stratified" in name and "contribution_per_booking" in name:
        return _fmt_eur(int(round(value)))
    return f"{value:,.4f}"


def _pretty_scenario(s: str) -> str:
    return {
        "standardise_on_control": "Standardise on control fee",
        "standardise_on_test": "Standardise on test fee",
    }.get(s, s)


def write_report(
    *,
    performance: PerformanceView,
    variance: VarianceView,
    ab_test: ABTestView,
    projection: ProjectionView,
    briefing: Briefing,
    consistency: ConsistencyReport,
    path: str | Path,
) -> Path:
    env = Environment(loader=BaseLoader(), autoescape=select_autoescape())
    env.globals["fmt_eur"] = _fmt_eur
    env.globals["fmt_pct"] = _fmt_pct
    env.globals["fmt_metric"] = _fmt_metric
    env.globals["fmt_driver"] = _fmt_driver
    env.globals["pretty_scenario"] = _pretty_scenario
    env.globals["origin_colour"] = lambda o: ORIGIN_COLOURS.get(o, "#eee")
    env.globals["origin_letter"] = lambda o: ORIGIN_LETTERS.get(o, "?")
    env.globals["origin_colours"] = ORIGIN_COLOURS
    env.globals["origin_letters"] = ORIGIN_LETTERS

    briefing_lines = briefing.rendered_text.split("\n")

    html = env.from_string(TEMPLATE).render(
        as_of_week=performance.as_of_week,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        consistency=consistency,
        briefing=briefing,
        briefing_lines=briefing_lines,
        performance=performance,
        variance=variance,
        ab=ab_test,
        projection=projection,
    )

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
