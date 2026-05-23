"""HTML report verification (T061, FR-026)."""
from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

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
def html_path(tmp_path_factory):
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
    out = tmp_path_factory.mktemp("exports") / "DA_Engine_test.html"
    write_report(
        performance=pv,
        variance=vv,
        ab_test=ab,
        projection=pj,
        briefing=briefing,
        consistency=consistency,
        path=out,
    )
    return out


@pytest.fixture(scope="module")
def soup(html_path):
    return BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")


def test_no_external_resources(soup) -> None:
    """FR-026 — single-file, no external assets."""
    # No external stylesheets
    for link in soup.find_all("link"):
        href = link.get("href", "")
        assert not href.startswith(("http://", "https://", "//")), (
            f"external link: {href}"
        )
    # No external scripts
    for script in soup.find_all("script"):
        src = script.get("src", "")
        assert not src, f"external script: {src}"
    # No external images
    for img in soup.find_all("img"):
        src = img.get("src", "")
        assert not src.startswith(("http://", "https://", "//")), (
            f"external img: {src}"
        )


def test_every_section_present(soup) -> None:
    for section_id in ("briefing", "performance", "variance", "ab-test", "projection"):
        assert soup.find(id=section_id) is not None, f"missing section #{section_id}"


def test_mode_badge_present(soup) -> None:
    """FR-024b — mode badge visible in the briefing section."""
    briefing = soup.find(id="briefing")
    badge = briefing.find(class_="mode-badge")
    assert badge is not None
    text = badge.get_text(strip=True)
    assert "LLM" in text or "template (fallback)" in text


def test_origin_pills_on_at_least_some_figures(soup) -> None:
    """FR-006 / FR-026 — origin tags preserved through to the report."""
    origins = soup.find_all(class_="origin")
    assert len(origins) > 0


def test_figure_data_ids_present(soup) -> None:
    """Each numeric figure carries a data-figure-id used by the PDF cross-check."""
    figures = soup.find_all(class_="figure")
    assert len(figures) >= 20  # plenty across all sections
    # Every figure has a data-figure-id
    assert all(f.get("data-figure-id") for f in figures)


def test_consistency_banner_present(soup) -> None:
    """Either pass or fail banner must appear."""
    banner = soup.find(class_="banner")
    assert banner is not None
    classes = banner.get("class", [])
    assert "pass" in classes or "fail" in classes
