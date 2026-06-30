"""M1 — URL discovery (SPEC §6.1).

Prefer declared URLs over blind crawling:
  1. robots.txt -> Sitemap: directives
  2. expand sitemaps via trafilatura
  3. fallback to a focused crawl only when no sitemap yields URLs
Then filter to content pages and cap at max_pages_per_domain.
"""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urlparse

from ..config import Config, config

# URL path fragments that almost never point at unique article content.
_NON_CONTENT_PAT = re.compile(
    r"""
    \.(?:jpg|jpeg|png|gif|svg|webp|ico|css|js|mjs|json|xml|rss|atom|pdf|zip|
        gz|mp4|mp3|woff2?|ttf|eot|map)(?:$|\?)   # asset extensions
    | /(?:tag|tags|category|categories|author|page|search|cart|checkout|
        login|signin|signup|account|wp-json|wp-admin|feed|amp)(?:/|$)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize_base(domain: str) -> str:
    """Turn 'example.com' or 'http://example.com/x' into 'https://example.com'."""
    domain = domain.strip()
    if not domain.startswith(("http://", "https://")):
        domain = "https://" + domain
    p = urlparse(domain)
    scheme = p.scheme or "https"
    return f"{scheme}://{p.netloc}"


def registrable_host(url: str) -> str:
    """Host without a leading 'www.' — used to keep discovery on-domain."""
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_content_url(url: str, base_host: str) -> bool:
    """Keep on-domain http(s) URLs that look like real content pages."""
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if registrable_host(url) != base_host:
        return False
    if _NON_CONTENT_PAT.search(url):
        return False
    return True


def _from_sitemaps(base: str) -> List[str]:
    try:
        from trafilatura.sitemaps import sitemap_search
    except Exception:
        return []
    try:
        urls = sitemap_search(base, target_lang=None)
        return list(urls or [])
    except Exception:
        return []


def _from_focused_crawl(base: str, max_pages: int) -> List[str]:
    try:
        from trafilatura.spider import focused_crawler
    except Exception:
        return []
    try:
        # focused_crawler handles robots, the frontier and dedup itself.
        to_visit, known = focused_crawler(
            base,
            max_seen_urls=max_pages,
            max_known_urls=max_pages * 5,
        )
        seen = set(known or [])
        seen.update(to_visit or [])
        return list(seen)
    except Exception:
        return []


def discover_urls(
    domain: str,
    max_pages: Optional[int] = None,
    cfg: Config = config,
) -> List[str]:
    """Return up to `max_pages` content URLs for a domain (sitemap first)."""
    cap = max_pages if max_pages is not None else cfg.max_pages_per_domain
    base = normalize_base(domain)
    base_host = registrable_host(base)

    candidates = _from_sitemaps(base)
    if not candidates:
        candidates = _from_focused_crawl(base, cap)

    # Filter, dedupe (stable order), and cap.
    seen = set()
    out: List[str] = []
    for u in candidates:
        if u in seen or not is_content_url(u, base_host):
            continue
        seen.add(u)
        out.append(u)
        if len(out) >= cap:
            break
    # Always include the homepage as a fallback seed.
    if base not in seen:
        out.insert(0, base)
    return out[:cap]


if __name__ == "__main__":  # quick manual check: python -m backend.pipeline.discover example.com
    import sys

    dom = sys.argv[1] if len(sys.argv) > 1 else "example.com"
    found = discover_urls(dom, max_pages=20)
    print(f"{len(found)} URLs for {dom}:")
    for u in found[:20]:
        print(" ", u)
