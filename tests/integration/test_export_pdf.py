"""PDF export verification (T063, FR-026)."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.config.loader import load_registry
from src.data.generator import generate_dataset
from src.engine.ab_test import compute_ab
from src.engine.briefing import compute_briefing
from src.engine.consistency import check_consistency
from src.engine.performance import compute_performance
from src.engine.projection import compute_projection
from src.engine.variance import compute_variance
from src.export.html_report import write_report

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "registry.yaml"


@pytest.fixture(scope="module")
def html_and_pdf(tmp_path_factory):
    try:
        import weasyprint  # noqa: F401  — verify native deps load
    except (ImportError, OSError) as exc:
        pytest.skip(
            f"WeasyPrint not loadable (native deps likely missing — see "
            f"quickstart.md): {exc}"
        )
    pytest.importorskip("pdfplumber")
    from src.export.pdf import write_pdf

    registry = load_registry(REGISTRY_PATH)
    df = generate_dataset(registry, write_parquet=False)
    pv = compute_performance(registry, df)
    vv = compute_variance(registry, df)
    ab = compute_ab(registry, df)
    pj = compute_projection(registry, df, ab)
    briefing = compute_briefing(pv, registry, force_template=True)
    consistency = check_consistency(
        performance=pv, variance=vv, ab_test=ab, bookings=df,
        registry=registry, projection=pj,
    )
    outdir = tmp_path_factory.mktemp("exports")
    html_path = outdir / "DA_Engine_test.html"
    write_report(
        performance=pv, variance=vv, ab_test=ab, projection=pj,
        briefing=briefing, consistency=consistency, registry=registry,
        path=html_path,
    )
    pdf_path = outdir / "DA_Engine_test.pdf"
    try:
        write_pdf(html_path, pdf_path)
    except (OSError, RuntimeError) as exc:
        # WeasyPrint native deps missing (cairo/pango/glib). See quickstart.md.
        pytest.skip(
            f"WeasyPrint native deps not installed (run brew install "
            f"cairo pango gdk-pixbuf libffi glib): {exc}"
        )
    return html_path, pdf_path


def test_pdf_file_exists_and_is_non_empty(html_and_pdf) -> None:
    _, pdf_path = html_and_pdf
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000  # non-trivially small


def test_pdf_contains_mode_badge_text(html_and_pdf) -> None:
    """Mode badge survives PDF rendering — provider-aware label set."""
    import pdfplumber

    _, pdf_path = html_and_pdf
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            extracted = page.extract_text() or ""
            text_parts.append(extracted)
    text = "\n".join(text_parts)
    assert (
        "deterministic fallback" in text
        or "Claude" in text
        or "Gemini" in text
    )


def test_pdf_contains_section_headings(html_and_pdf) -> None:
    import pdfplumber

    _, pdf_path = html_and_pdf
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    for keyword in ("Performance", "Variance", "Projection"):
        assert keyword in text, f"PDF missing section heading: {keyword}"
