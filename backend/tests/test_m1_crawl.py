"""M1 unit checks that don't need the network: URL filtering, extraction,
and page storage. A live end-to-end crawl is exercised via `make crawl`."""
from pathlib import Path

from backend.config import Config
from backend.db import get_connection, init_db
from backend.pipeline.discover import is_content_url, normalize_base, registrable_host
from backend.pipeline.extract import extract_page
from backend.pipeline.run import create_run, get_domains, _store_pages


def test_normalize_and_host():
    assert normalize_base("example.com") == "https://example.com"
    assert normalize_base("http://www.example.com/x") == "http://www.example.com"
    assert registrable_host("https://www.example.com/a") == "example.com"


def test_is_content_url_filters_assets_and_offdomain():
    h = "example.com"
    assert is_content_url("https://example.com/blog/post", h)
    assert not is_content_url("https://example.com/logo.png", h)
    assert not is_content_url("https://example.com/tag/news", h)
    assert not is_content_url("https://other.com/blog/post", h)


def test_extract_page_from_html():
    body = " ".join(
        ["Gantt charts help teams plan project timelines and milestones."] * 12
    )
    html = f"<html><head><title>Planning Guide</title></head><body><article><h1>Planning</h1><p>{body}</p></article></body></html>"
    page = extract_page(html, "https://example.com/planning", market_language="en")
    assert page is not None
    assert page.text and "Gantt" in page.text
    assert page.lang == "en"


def test_store_pages_roundtrip(tmp_path: Path):
    cfg = Config(db_path=tmp_path / "m1.db")
    init_db(cfg.db_path)
    run_id = create_run("example.com", ["rival.com"], "en", 50, cfg=cfg)
    dom = get_domains(run_id, cfg=cfg)[0]
    n = _store_pages(
        dom["id"],
        [{"url": "https://example.com/p", "title": "P", "text": "hello world", "lang": "en", "etag": None}],
        cfg,
    )
    assert n == 1
    conn = get_connection(cfg.db_path)
    try:
        row = conn.execute("SELECT url, text FROM pages").fetchone()
    finally:
        conn.close()
    assert row["url"] == "https://example.com/p"
    assert row["text"] == "hello world"
