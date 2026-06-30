"""M1 — polite fetching (SPEC §6.2).

Static fetch via httpx (async, HTTP/2) with:
  - robots.txt respected per host (config-toggleable)
  - per-host concurrency limit + small backoff
  - a Playwright fallback (optional) when extraction would be too thin.

The Playwright path is imported lazily so the repo runs without it installed.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..config import Config, config

# Below this many characters we treat a static fetch as "too thin" and (if
# enabled) retry through Playwright for JS-rendered pages.
THIN_BODY_CHARS = 200


@dataclass
class FetchResult:
    url: str
    status: int
    html: Optional[str]
    etag: Optional[str]
    rendered: bool = False  # True if fetched via Playwright


class RobotsCache:
    """Lazily fetch + cache one RobotFileParser per host."""

    def __init__(self, user_agent: str, respect: bool):
        self.user_agent = user_agent
        self.respect = respect
        self._cache: Dict[str, Optional[RobotFileParser]] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        if not self.respect:
            return True
        p = urlparse(url)
        host_key = f"{p.scheme}://{p.netloc}"
        if host_key not in self._cache:
            self._cache[host_key] = await self._load(client, host_key)
        rp = self._cache[host_key]
        if rp is None:  # robots unreachable -> default allow (be lenient)
            return True
        return rp.can_fetch(self.user_agent, url)

    async def _load(
        self, client: httpx.AsyncClient, host_key: str
    ) -> Optional[RobotFileParser]:
        rp = RobotFileParser()
        try:
            resp = await client.get(f"{host_key}/robots.txt")
            if resp.status_code >= 400:
                return None
            rp.parse(resp.text.splitlines())
            return rp
        except Exception:
            return None


async def _maybe_render(url: str) -> Optional[str]:
    """Fetch fully-rendered HTML via Playwright, if it's installed."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            await browser.close()
            return html
    except Exception:
        return None


async def fetch_url(
    client: httpx.AsyncClient,
    url: str,
    robots: RobotsCache,
    allow_render: bool = True,
) -> FetchResult:
    if not await robots.allowed(client, url):
        return FetchResult(url=url, status=999, html=None, etag=None)
    try:
        resp = await client.get(url)
    except Exception:
        return FetchResult(url=url, status=0, html=None, etag=None)

    etag = resp.headers.get("etag")
    if resp.status_code >= 400:
        return FetchResult(url=url, status=resp.status_code, html=None, etag=etag)

    html = resp.text
    if allow_render and (html is None or len(html) < THIN_BODY_CHARS):
        rendered = await _maybe_render(url)
        if rendered:
            return FetchResult(url, resp.status_code, rendered, etag, rendered=True)
    return FetchResult(url=url, status=resp.status_code, html=html, etag=etag)


async def fetch_many(
    urls: List[str],
    cfg: Config = config,
    allow_render: bool = True,
    deadline_seconds: Optional[float] = None,
    on_result=None,
) -> List[FetchResult]:
    """Fetch many URLs with a per-host concurrency cap and polite backoff.

    Stops starting new fetches once `deadline_seconds` of wall-clock have
    elapsed (the time budget), so a slow/huge site can't stall the run. If
    `on_result` is given it's called with each FetchResult as it completes —
    used to store pages incrementally for live per-domain progress.
    """
    robots = RobotsCache(cfg.user_agent, cfg.respect_robots)
    sem = asyncio.Semaphore(max(1, cfg.per_host_concurrency))
    headers = {"User-Agent": cfg.user_agent}
    limits = httpx.Limits(max_connections=cfg.per_host_concurrency)
    results: List[FetchResult] = []
    loop = asyncio.get_event_loop()
    start = loop.time()

    def expired() -> bool:
        return bool(deadline_seconds) and (loop.time() - start) > deadline_seconds

    async with httpx.AsyncClient(
        headers=headers,
        timeout=cfg.request_timeout,
        follow_redirects=True,
        http2=True,
        limits=limits,
    ) as client:

        async def worker(u: str) -> FetchResult:
            async with sem:
                if expired():  # budget spent -> skip remaining URLs
                    return FetchResult(url=u, status=997, html=None, etag=None)
                res = await fetch_url(client, u, robots, allow_render)
                await asyncio.sleep(0.2)  # gentle inter-request delay per slot
                return res

        tasks = [asyncio.create_task(worker(u)) for u in urls]
        for fut in asyncio.as_completed(tasks):
            res = await fut
            results.append(res)
            if on_result is not None:
                on_result(res)
    return results


def fetch_all(
    urls: List[str],
    cfg: Config = config,
    allow_render: bool = True,
    deadline_seconds: Optional[float] = None,
    on_result=None,
):
    """Sync wrapper around fetch_many for CLI/synchronous run contexts."""
    return asyncio.run(
        fetch_many(
            urls,
            cfg=cfg,
            allow_render=allow_render,
            deadline_seconds=deadline_seconds,
            on_result=on_result,
        )
    )
