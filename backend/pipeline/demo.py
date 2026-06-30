"""Deterministic demo corpus (dev/verification only).

Seeds a run with one own domain + three competitors and a handful of themed
pages each, then runs the real M2→M4 pipeline on it. Topics are still
*discovered* by clustering this seeded content (no hardcoded topic list) — the
seeder only stands in for the crawl so the pipeline can be exercised offline,
reproducibly, and across multiple domains (which the live single-domain crawl
can't show). Page counts per (domain, theme) are tuned so all five coverage
states arise.

Run:  python -m backend.pipeline.demo
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..config import Config, config
from ..db import get_connection, init_db
from .chunk_embed import embed_run
from .coverage import score_coverage
from .run import create_run, get_domains, set_run_status
from .topics import discover_topics

OWN = "acme.com"
COMPETITORS = ["rival.com", "boards.com", "notewise.com"]

# Each theme: distinct vocabulary so it forms its own cluster, plus a per-domain
# page allocation engineered to produce a spread of coverage states.
THEMES: Dict[str, Dict] = {
    "gantt": {
        "text": (
            "Gantt charts visualise the project timeline as horizontal bars across a "
            "schedule. Plan milestones, set task dependencies, and track the critical "
            "path. A timeline view shows start and end dates so teams can sequence work "
            "and adjust deadlines when the schedule slips."
        ),
        "pages": {"acme.com": 5, "rival.com": 2, "boards.com": 1, "notewise.com": 0},
    },
    "integrations": {
        "text": (
            "Connect the app to Slack, Microsoft Teams, and Google Drive. Integrations "
            "push notifications to channels, sync files, and let you create tasks from a "
            "message. The integration directory lists hundreds of connected apps for your "
            "workflow."
        ),
        "pages": {"acme.com": 3, "rival.com": 3, "boards.com": 2, "notewise.com": 0},
    },
    "api": {
        "text": (
            "The public REST API exposes endpoints for tasks, projects, and users. "
            "Authenticate with an OAuth token, paginate results, and subscribe to "
            "webhooks for real-time events. Developers can build custom integrations and "
            "automate workflows against the API."
        ),
        "pages": {"acme.com": 0, "rival.com": 4, "boards.com": 3, "notewise.com": 0},
    },
    "ai": {
        "text": (
            "AI features summarise long threads, draft status updates, and auto-prioritise "
            "tasks. The assistant uses machine learning to surface smart suggestions, "
            "generate meeting notes, and answer questions about your projects with natural "
            "language search."
        ),
        "pages": {"acme.com": 1, "rival.com": 4, "boards.com": 3, "notewise.com": 0},
    },
    "templates": {
        "text": (
            "Get started fast with ready-made templates for marketing calendars, sprint "
            "planning, and onboarding checklists. Each template includes sample tasks and "
            "a guided setup so new teams can onboard quickly and customise the workspace "
            "to their process."
        ),
        "pages": {"acme.com": 5, "rival.com": 0, "boards.com": 0, "notewise.com": 0},
    },
    "mobile": {
        "text": (
            "The mobile app for iOS and Android lets you manage work on the go. Get push "
            "notifications, update tasks offline, and review your day from your phone. The "
            "native mobile experience keeps everything in sync across devices."
        ),
        "pages": {"acme.com": 3, "rival.com": 2, "boards.com": 0, "notewise.com": 0},
    },
    "capacity": {
        "text": (
            "Resource and capacity planning balances team workload across projects. See "
            "who is over capacity, allocate people to assignments, and forecast staffing "
            "needs. Workload management highlights bottlenecks so managers can rebalance "
            "resources."
        ),
        "pages": {"acme.com": 0, "rival.com": 0, "boards.com": 4, "notewise.com": 3},
    },
}


def _page_text(base: str, theme: str, idx: int) -> str:
    """Slight per-page variation so chunks aren't byte-identical."""
    return (
        f"# {theme.title()} guide (part {idx + 1})\n\n{base}\n\n"
        f"This article (#{idx + 1}) explains {theme} in depth for teams adopting it."
    )


def seed_demo(cfg: Config = config) -> int:
    init_db(cfg.db_path)
    run_id = create_run(OWN, COMPETITORS, "en", cfg.max_pages_per_domain, cfg=cfg)
    dom_id = {d["domain"]: d["id"] for d in get_domains(run_id, cfg=cfg)}

    conn = get_connection(cfg.db_path)
    try:
        for theme, spec in THEMES.items():
            for domain, n in spec["pages"].items():
                for i in range(n):
                    conn.execute(
                        "INSERT INTO pages (domain_id, url, title, text, lang) "
                        "VALUES (?,?,?,?,?)",
                        (
                            dom_id[domain],
                            f"https://{domain}/{theme}/{i + 1}",
                            f"{theme.title()} guide {i + 1}",
                            _page_text(spec["text"], theme, i),
                            "en",
                        ),
                    )
        conn.commit()
    finally:
        conn.close()
    return run_id


def run_demo(cfg: Config = config) -> int:
    run_id = seed_demo(cfg)
    n_chunks = embed_run(run_id, cfg=cfg)
    n_topics, n_cats = discover_topics(run_id, cfg=cfg)
    n_scored = score_coverage(run_id, cfg=cfg)
    set_run_status(run_id, "done", cfg=cfg)
    print(
        f"demo run {run_id}: {n_chunks} chunks, {n_topics} topics, "
        f"{n_cats} categories, {n_scored} scored"
    )
    return run_id


if __name__ == "__main__":
    run_demo()
