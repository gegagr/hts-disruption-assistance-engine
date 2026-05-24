"""HTML → PDF via WeasyPrint (FR-026 — content-equivalent to HTML).

WeasyPrint pulls in native cairo / pango / glib via cffi at import time. If
those libs aren't installed we fail loudly with a clear, actionable message
so the user knows what to fix (rather than silently producing nothing).
"""
from __future__ import annotations

from pathlib import Path

_WEASYPRINT_HINT = (
    "WeasyPrint failed to load its native dependencies. Install with:\n"
    "  macOS:  brew install cairo pango gdk-pixbuf libffi glib\n"
    "  Debian: apt install libcairo2 libpango-1.0-0 libpangocairo-1.0-0 "
    "libgdk-pixbuf2.0-0 libffi-dev"
)


def write_pdf(html_path: str | Path, pdf_path: str | Path) -> Path:
    """Convert *html_path* to a PDF at *pdf_path*. Same content by construction.

    Raises:
        RuntimeError: if WeasyPrint or its native deps are unavailable; the
            message tells the user what to install.
    """
    try:
        from weasyprint import HTML  # local import — heavy native dependency
    except (ImportError, OSError) as exc:
        raise RuntimeError(f"{_WEASYPRINT_HINT}\n\nUnderlying error: {exc}") from exc

    html_path = Path(html_path)
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(filename=str(html_path)).write_pdf(str(pdf_path))
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        raise RuntimeError(
            f"WeasyPrint produced no output at {pdf_path}. Check the source "
            "HTML for malformed CSS or missing assets."
        )
    return pdf_path
