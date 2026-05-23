"""Export CLI verification (T065)."""
from __future__ import annotations

import pytest

from src.cli.export import main as cli_main
from src.config.loader import load_registry
from src.data.generator import generate_dataset


@pytest.fixture(scope="module")
def populated_dataset(tmp_path_factory):
    """Ensure data/generated/ has a dataset for the CLI to consume."""
    registry = load_registry()
    generate_dataset(registry, write_parquet=True)
    return True


def test_cli_xlsx_html_no_llm(populated_dataset, tmp_path) -> None:
    rc = cli_main([
        "--xlsx",
        "--html",
        "--no-llm",
        "--out",
        str(tmp_path),
    ])
    assert rc == 0
    xlsx_files = list(tmp_path.glob("*.xlsx"))
    html_files = list(tmp_path.glob("*.html"))
    assert len(xlsx_files) == 1
    assert len(html_files) == 1
    # Mode badge present in HTML (template fallback)
    text = html_files[0].read_text(encoding="utf-8")
    assert "template (fallback)" in text


def test_cli_no_format_flag_returns_error(populated_dataset, tmp_path) -> None:
    rc = cli_main(["--out", str(tmp_path)])
    assert rc == 1


def test_cli_specific_as_of_week(populated_dataset, tmp_path) -> None:
    rc = cli_main([
        "--xlsx",
        "--no-llm",
        "--as-of-week", "20",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    files = list(tmp_path.glob("*.xlsx"))
    assert any("w020" in f.name for f in files)


def test_cli_pdf_flag_auto_includes_html(populated_dataset, tmp_path) -> None:
    """--pdf without --html should still produce HTML (the PDF source)."""
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        pytest.skip("WeasyPrint not loadable")
    rc = cli_main([
        "--pdf",
        "--no-llm",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    assert list(tmp_path.glob("*.html"))
    assert list(tmp_path.glob("*.pdf"))
