"""Export CLI — produce XLSX / HTML / PDF artefacts.

Usage::

    python -m src.cli.export --xlsx --html --pdf --out exports/ [--no-llm] [--as-of-week N]

Exit codes:
  0  success
  2  consistency check failed (no artefacts written)
  3  registry validation failed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config.loader import RegistryLoadError, load_registry
from src.engine.ab_test import compute_ab
from src.engine.briefing import compute_briefing
from src.engine.consistency import check_consistency
from src.engine.dataset import load_bookings, max_iso_week
from src.engine.performance import compute_performance
from src.engine.projection import compute_projection
from src.engine.variance import compute_variance
from src.export import html_report as html_mod
from src.export import xlsx as xlsx_mod


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--xlsx", action="store_true", help="Write the XLSX workbook")
    p.add_argument("--html", action="store_true", help="Write the HTML report")
    p.add_argument("--pdf", action="store_true", help="Write the PDF (derived from HTML)")
    p.add_argument(
        "--as-of-week",
        type=int,
        default=None,
        help="Anchor week (defaults to last week in the dataset).",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=Path("exports"),
        help="Output directory (default: exports/).",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Force template fallback (no LLM call). Use for reproducible runs / CI.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not (args.xlsx or args.html or args.pdf):
        print("ERROR: at least one of --xlsx / --html / --pdf required.", file=sys.stderr)
        return 1
    if args.pdf and not args.html:
        # PDF derives from HTML; auto-include
        args.html = True

    try:
        registry = load_registry()
    except RegistryLoadError as exc:
        print(f"ERROR (registry): {exc}", file=sys.stderr)
        return 3

    bookings = load_bookings()
    as_of_week = args.as_of_week if args.as_of_week is not None else max_iso_week(bookings)

    pv = compute_performance(registry, bookings, as_of_week=as_of_week)
    vv = compute_variance(registry, bookings, as_of_week=as_of_week)
    ab = compute_ab(registry, bookings, as_of_week=as_of_week)
    pj = compute_projection(registry, bookings, ab, as_of_week=as_of_week)
    briefing = compute_briefing(pv, registry, force_template=args.no_llm)
    consistency = check_consistency(
        performance=pv,
        variance=vv,
        ab_test=ab,
        bookings=bookings,
        registry=registry,
        projection=pj,
    )

    if not consistency.passed:
        print(
            f"ERROR: consistency check FAILED — {len(consistency.discrepancies)} "
            "discrepancies. No artefacts written.",
            file=sys.stderr,
        )
        for d in consistency.discrepancies:
            print(
                f"  - {d.check.name}: {d.check.lhs_label}={d.check.lhs_value:,} "
                f"vs {d.check.rhs_label}={d.check.rhs_value:,} (Δ {d.delta:+,})",
                file=sys.stderr,
            )
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    label = f"DA_Engine_w{as_of_week:03d}"

    if args.xlsx:
        path = args.out / f"{label}.xlsx"
        xlsx_mod.write_workbook(
            registry=registry,
            bookings_df=bookings,
            performance=pv,
            variance=vv,
            ab_test=ab,
            projection=pj,
            briefing=briefing,
            consistency=consistency,
            path=path,
        )
        print(f"wrote {path}")

    html_path = None
    if args.html:
        html_path = args.out / f"{label}.html"
        html_mod.write_report(
            performance=pv,
            variance=vv,
            ab_test=ab,
            projection=pj,
            briefing=briefing,
            consistency=consistency,
            registry=registry,
            path=html_path,
        )
        print(f"wrote {html_path}")

    if args.pdf:
        from src.export.pdf import write_pdf

        pdf_path = args.out / f"{label}.pdf"
        write_pdf(html_path, pdf_path)
        print(f"wrote {pdf_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
