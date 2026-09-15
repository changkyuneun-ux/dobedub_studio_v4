"""Server-compatible batch split adapter.

This module keeps the original webtoon panel splitter dependency visible inside
the deployable backend package.  The source prototype lived at
``/Users/changkyuneun/webtoon Pannel/batch_split.py`` and orchestrated:

1. PDF page rendering with ``pdftoppm``.
2. Panel detection through ``grid_split.split_panels``.
3. Full-page fallback crop when no panels are detected.

The production API uses ``runtime.py`` for job-scoped S3/DB persistence, but the
core rendering/splitting helpers are re-exported here so the packaged server has
the expected ``batch_split`` dependency boundary without importing a local-only
CLI script.
"""

from __future__ import annotations

from backend.app.services.webtoon_panel_engine.runtime import (
    CutResult,
    RenderedUnitResult,
    page_count,
    process_image_file,
    process_pdf_page,
)

__all__ = [
    "CutResult",
    "RenderedUnitResult",
    "page_count",
    "process_image_file",
    "process_pdf_page",
]
