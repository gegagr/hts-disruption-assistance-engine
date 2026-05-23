"""HTML → PDF via WeasyPrint (FR-026 — content-equivalent to HTML)."""
from __future__ import annotations

from pathlib import Path


def write_pdf(html_path: str | Path, pdf_path: str | Path) -> Path:
    """Convert *html_path* to a PDF at *pdf_path*. Same content by construction."""
    from weasyprint import HTML  # local import — heavy native dependency

    html_path = Path(html_path)
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    return pdf_path
