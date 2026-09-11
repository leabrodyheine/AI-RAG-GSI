"""Unit test for the on-disk HTML cache in orswater.fetch (no real network calls)."""

from __future__ import annotations

import orswater.fetch as fetch_module


def test_fetch_chapter_uses_cache_and_skips_network(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_module, "CACHE_DIR", tmp_path)
    cached_html = "<html>cached content</html>"
    (tmp_path / "ors536.html").write_text(cached_html, encoding=fetch_module.ENCODING)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.get should not be called when the cache has a hit")

    monkeypatch.setattr(fetch_module.httpx, "get", fail_if_called)

    assert fetch_module.fetch_chapter(536) == cached_html


def test_fetch_chapter_writes_cache_after_a_network_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_module, "CACHE_DIR", tmp_path)

    class FakeResponse:
        content = "<html>fresh content</html>".encode(fetch_module.ENCODING)

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fetch_module.httpx, "get", lambda *a, **k: FakeResponse())

    html = fetch_module.fetch_chapter(537)
    assert html == "<html>fresh content</html>"
    assert (tmp_path / "ors537.html").read_text(encoding=fetch_module.ENCODING) == html
