"""Fetch ORS chapter pages, caching the raw HTML in a gitignored folder.

Each chapter is one page: ``https://www.oregonlegislature.gov/bills_laws/ors/ors<chapter>.html``.
The page is a Word export served as ``charset=windows-1252``.
"""

from __future__ import annotations

import pathlib

import httpx

BASE_URL = "https://www.oregonlegislature.gov/bills_laws/ors/ors{chapter}.html"
CACHE_DIR = pathlib.Path(__file__).resolve().parents[2] / ".cache"
ENCODING = "cp1252"


def fetch_chapter(chapter: int, *, use_cache: bool = True, timeout: float = 30.0) -> str:
    """Return the HTML text for one ORS chapter, using the on-disk cache when present."""
    cache_path = CACHE_DIR / f"ors{chapter}.html"
    if use_cache and cache_path.exists():
        return cache_path.read_text(encoding=ENCODING)

    url = BASE_URL.format(chapter=chapter)
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    html = response.content.decode(ENCODING)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding=ENCODING)
    return html
