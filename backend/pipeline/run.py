"""Run orchestration (SPEC §5).

For M1 this stores runs/domains and crawls one domain into `pages`. Later
milestones extend `run_pipeline` to chunk/embed (M2), discover topics (M3) and
score coverage (M4). The CLI (`make crawl DOMAIN=...`) exercises just the crawl.
"""
from __future__ import annotations

import json
from typing import List, Optional

from ..config import Config, config
from ..db import get_connection, init_db
from .chunk_embed import embed_run
from .coverage import score_coverage
from .discover import discover_urls
from .extract import extract_page
from .fetch import fetch_all
from .topics import discover_topics


# --- DB write helpers -------------------------------------------------------

def create_run(
    own_domain: str,
    competitor_domains: List[str],
    market_language: str,
    max_pages: int,
    cfg: Config = config,
) -> int:
    init_db(cfg.db_path)
    conn = get_connection(cfg.db_path)
    try:
        cur = conn.execute(
            """INSERT INTO runs
               (own_domain, competitor_domains_json, market_language, max_pages, status)
               VALUES (?, ?, ?, ?, 'running')""",
            (own_domain, json.dumps(competitor_domains), market_language, max_pages),
        )
        run_id = cur.lastrowid
        conn.execute(
            "INSERT INTO domains (run_id, domain, is_own) VALUES (?, ?, 1)",
            (run_id, own_domain),
        )
        for comp in competitor_domains:
            conn.execute(
                "INSERT INTO domains (run_id, domain, is_own) VALUES (?, ?, 0)",
                (run_id, comp),
            )
        conn.commit()
        return run_id
    finally:
        conn.close()


def set_run_status(run_id: int, status: str, cfg: Config = config) -> None:
    conn = get_connection(cfg.db_path)
    try:
        if status in ("done", "error"):
            conn.execute(
                "UPDATE runs SET status=?, finished_at=datetime('now') WHERE id=?",
                (status, run_id),
            )
        else:
            conn.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))
        conn.commit()
    finally:
        conn.close()


def get_domains(run_id: int, cfg: Config = config):
    conn = get_connection(cfg.db_path)
    try:
        return conn.execute(
            "SELECT id, domain, is_own FROM domains WHERE run_id=? ORDER BY is_own DESC, id",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()


def _store_pages(domain_id: int, pages, cfg: Config) -> int:
    conn = get_connection(cfg.db_path)
    try:
        n = 0
        for pg in pages:
            conn.execute(
                """INSERT INTO pages (domain_id, url, title, text, lang, etag)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (domain_id, pg["url"], pg["title"], pg["text"], pg["lang"], pg.get("etag")),
            )
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


# --- M1 crawl ---------------------------------------------------------------

def crawl_domain(
    domain_id: int,
    domain: str,
    market_language: str,
    max_pages: Optional[int] = None,
    cfg: Config = config,
) -> int:
    """Discover → fetch → extract → store pages for one domain. Returns count.

    Pages are stored incrementally as each fetch completes, so per-domain page
    counts update live during the crawl. Crawling stops at the time budget.
    """
    urls = discover_urls(domain, max_pages=max_pages, cfg=cfg)
    budget = cfg.crawl_time_budget_seconds or None

    conn = get_connection(cfg.db_path)
    stored = {"n": 0}

    def handle(res):
        if not res.html:
            return
        page = extract_page(res.html, res.url, market_language=market_language)
        if page is None:
            return
        conn.execute(
            "INSERT INTO pages (domain_id, url, title, text, lang, etag) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (domain_id, page.url, page.title, page.text, page.lang, res.etag),
        )
        conn.commit()
        stored["n"] += 1

    try:
        fetch_all(urls, cfg=cfg, deadline_seconds=budget, on_result=handle)
    finally:
        conn.close()
    return stored["n"]


def get_run(run_id: int, cfg: Config = config):
    conn = get_connection(cfg.db_path)
    try:
        return conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    finally:
        conn.close()


def execute_run(run_id: int, cfg: Config = config) -> int:
    """Run all pipeline stages (M1→M4) for an already-created run."""
    run = get_run(run_id, cfg=cfg)
    if run is None:
        raise ValueError(f"run {run_id} not found")
    lang = run["market_language"]
    cap = run["max_pages"]
    set_run_status(run_id, "running", cfg=cfg)
    try:
        for d in get_domains(run_id, cfg=cfg):
            n = crawl_domain(d["id"], d["domain"], lang, max_pages=cap, cfg=cfg)
            print(f"  [{d['domain']}] stored {n} pages")
        set_run_status(run_id, "crawled", cfg=cfg)

        # M2 — chunk + embed every page across all domains.
        n_chunks = embed_run(run_id, cfg=cfg)
        print(f"  embedded {n_chunks} chunks")
        set_run_status(run_id, "embedded", cfg=cfg)

        # M3 — discover topics + categories over all chunks (global).
        n_topics, n_cats = discover_topics(run_id, cfg=cfg)
        print(f"  discovered {n_topics} topics in {n_cats} categories")
        set_run_status(run_id, "topiced", cfg=cfg)

        # M4 — coverage strength, share, and state per topic.
        n_scored = score_coverage(run_id, cfg=cfg)
        print(f"  scored coverage for {n_scored} topics")
        set_run_status(run_id, "done", cfg=cfg)
    except Exception:
        set_run_status(run_id, "error", cfg=cfg)
        raise
    return run_id


def run_pipeline(
    own_domain: str,
    competitor_domains: List[str],
    market_language: Optional[str] = None,
    max_pages: Optional[int] = None,
    cfg: Config = config,
) -> int:
    """Create a run and execute the full pipeline (M1→M4) synchronously."""
    lang = market_language or cfg.default_market_language
    cap = max_pages if max_pages is not None else cfg.max_pages_per_domain
    run_id = create_run(own_domain, competitor_domains, lang, cap, cfg=cfg)
    return execute_run(run_id, cfg=cfg)


# --- CLI (make crawl DOMAIN=example.com) ------------------------------------

def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Crawl one domain (M1 debug).")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--lang", default=None)
    args = parser.parse_args()

    lang = args.lang or config.default_market_language
    cap = args.max_pages if args.max_pages is not None else config.max_pages_per_domain

    run_id = create_run(args.domain, [], lang, cap)
    dom = get_domains(run_id)[0]
    print(f"Run {run_id}: crawling {args.domain} (cap {cap}, lang {lang})…")
    n = crawl_domain(dom["id"], args.domain, lang, max_pages=cap)
    set_run_status(run_id, "crawled")
    print(f"Done. Stored {n} pages with non-empty text for {args.domain}.")


if __name__ == "__main__":
    _main()
