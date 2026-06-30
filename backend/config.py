"""Central configuration for Topic Coverage.

Every threshold, cap, and model choice lives here (CLAUDE.md hard rule:
"All thresholds in config.py — never hardcoded in logic"). Values default to
something that runs fully locally with no API keys, and each is overridable
via an environment variable (and therefore via `.env`, loaded below).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

try:  # .env is optional; defaults stand on their own.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a declared dep, but stay safe
    pass


# --- small env helpers -------------------------------------------------------

def _env_str(key: str, default: str) -> str:
    val = os.getenv(key)
    return val if val is not None and val != "" else default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Project root = the repo dir (parent of backend/).
ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    # --- storage ---
    db_path: Path = field(
        default_factory=lambda: (
            Path(_env_str("TC_DB_PATH", str(ROOT_DIR / "data" / "topic_coverage.db")))
        )
    )

    # --- crawl politeness / caps (SPEC §6.1–6.2) ---
    max_pages_per_domain: int = field(
        default_factory=lambda: _env_int("TC_MAX_PAGES_PER_DOMAIN", 300)
    )
    per_host_concurrency: int = field(
        default_factory=lambda: _env_int("TC_PER_HOST_CONCURRENCY", 4)
    )
    request_timeout: float = field(
        default_factory=lambda: _env_float("TC_REQUEST_TIMEOUT", 20.0)
    )
    user_agent: str = field(
        default_factory=lambda: _env_str(
            "TC_USER_AGENT",
            "TopicCoverageBot/0.1 (+https://example.com/bot)",
        )
    )
    respect_robots: bool = field(
        default_factory=lambda: _env_bool("TC_RESPECT_ROBOTS", True)
    )
    # Per-domain wall-clock budget for crawling. Once exceeded, remaining URLs
    # are skipped so one slow/huge site can't stall a run. 0 = no time limit.
    crawl_time_budget_seconds: float = field(
        default_factory=lambda: _env_float("TC_CRAWL_TIME_BUDGET", 180.0)
    )
    # Hard cap on the sitemap-less focused-crawl fallback (live crawling is
    # slow). Sites WITH a sitemap aren't affected by this.
    focused_crawl_max_urls: int = field(
        default_factory=lambda: _env_int("TC_FOCUSED_CRAWL_MAX_URLS", 80)
    )
    # Wall-clock limit on the focused-crawl fallback itself (it has no internal
    # timeout and can hang on slow sites). On timeout we proceed with whatever
    # URLs we have (at least the homepage). 0 = no limit.
    focused_crawl_timeout_seconds: float = field(
        default_factory=lambda: _env_float("TC_FOCUSED_CRAWL_TIMEOUT", 45.0)
    )

    # --- chunking / embeddings (SPEC §6.4) ---
    chunk_min_tokens: int = field(
        default_factory=lambda: _env_int("TC_CHUNK_MIN_TOKENS", 200)
    )
    chunk_max_tokens: int = field(
        default_factory=lambda: _env_int("TC_CHUNK_MAX_TOKENS", 500)
    )
    chunk_overlap_tokens: int = field(
        default_factory=lambda: _env_int("TC_CHUNK_OVERLAP_TOKENS", 40)
    )
    embedding_backend: str = field(
        default_factory=lambda: _env_str("TC_EMBEDDING_BACKEND", "local")
    )
    local_embedding_model: str = field(
        default_factory=lambda: _env_str(
            "TC_LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
        )
    )

    # --- topic discovery (SPEC §6.4) ---
    min_cluster_size: int = field(
        default_factory=lambda: _env_int("TC_MIN_CLUSTER_SIZE", 8)
    )
    umap_n_neighbors: int = field(
        default_factory=lambda: _env_int("TC_UMAP_N_NEIGHBORS", 15)
    )
    num_categories_min: int = field(
        default_factory=lambda: _env_int("TC_NUM_CATEGORIES_MIN", 8)
    )
    num_categories_max: int = field(
        default_factory=lambda: _env_int("TC_NUM_CATEGORIES_MAX", 14)
    )

    # --- coverage scoring (SPEC §6.5–6.6) ---
    sim_threshold: float = field(
        default_factory=lambda: _env_float("TC_SIM_THRESHOLD", 0.35)
    )
    parity_delta: float = field(
        default_factory=lambda: _env_float("TC_PARITY_DELTA", 0.10)
    )

    # --- optional hosted upgrades ---
    openai_api_key: str = field(
        default_factory=lambda: _env_str("OPENAI_API_KEY", "")
    )
    llm_labels: bool = field(
        default_factory=lambda: _env_bool("TC_LLM_LABELS", False)
    )

    # --- language ---
    default_market_language: str = field(
        default_factory=lambda: _env_str("TC_MARKET_LANGUAGE", "en")
    )

    def ensure_dirs(self) -> None:
        """Create any directories the config implies (e.g. the DB folder)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


# The 5 coverage states and their colours (SPEC §2). Kept here so both the API
# and any server-side rendering share one source of truth with the frontend.
STATE_COLORS = {
    "only_you": "#15803d",
    "you_lead": "#22c55e",
    "even": "#94a3b8",
    "comp_lead": "#fb923c",
    "only_comp": "#ef4444",
}
COVERAGE_STATES: List[str] = list(STATE_COLORS.keys())


# A single shared instance. Import `config` everywhere.
config = Config()
