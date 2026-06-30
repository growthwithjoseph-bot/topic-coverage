"""M1 — content extraction (SPEC §6.3).

trafilatura is the primary extractor (markdown + metadata). We keep the page
title and URL as evidence, and language-detect with lingua to drop pages that
aren't in the run's market language.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Below this many characters of extracted text, a page isn't worth keeping.
MIN_TEXT_CHARS = 200


@dataclass
class ExtractedPage:
    url: str
    title: Optional[str]
    text: Optional[str]
    lang: Optional[str]


def extract_content(html: str, url: str) -> Optional[ExtractedPage]:
    """Extract clean main content from HTML. Returns None if too thin."""
    if not html:
        return None
    try:
        import trafilatura
        from trafilatura.metadata import extract_metadata
    except Exception:
        return None

    text = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if not text or len(text) < MIN_TEXT_CHARS:
        return None

    title = None
    try:
        meta = extract_metadata(html, default_url=url)
        if meta is not None:
            title = meta.title
    except Exception:
        title = None

    return ExtractedPage(url=url, title=title, text=text, lang=None)


# --- language detection (lingua) -------------------------------------------

_DETECTOR = None


def _get_detector():
    global _DETECTOR
    if _DETECTOR is not None:
        return _DETECTOR
    try:
        from lingua import LanguageDetectorBuilder

        _DETECTOR = LanguageDetectorBuilder.from_all_languages().build()
    except Exception:
        _DETECTOR = None
    return _DETECTOR


def detect_language(text: str) -> Optional[str]:
    """Return an ISO-639-1 code (e.g. 'en') or None if undetectable."""
    if not text:
        return None
    detector = _get_detector()
    if detector is None:
        return None
    try:
        lang = detector.detect_language_of(text[:2000])
        if lang is None:
            return None
        return lang.iso_code_639_1.name.lower()
    except Exception:
        return None


def extract_page(
    html: str, url: str, market_language: Optional[str] = "en"
) -> Optional[ExtractedPage]:
    """Full extract + language filter. None if thin or wrong language."""
    page = extract_content(html, url)
    if page is None:
        return None
    page.lang = detect_language(page.text)
    if market_language and page.lang and page.lang != market_language.lower():
        return None
    return page
