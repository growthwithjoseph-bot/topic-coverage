"""FastAPI application for Topic Coverage (SPEC §8).

Endpoints:
  GET  /health
  POST /runs                     start an analysis (runs in the background)
  GET  /runs/{id}                status + counts
  GET  /runs/{id}/map            the category→topic coverage tree
  GET  /runs/{id}/topics/{tid}   per-topic detected content

A run executes in a background thread so POST returns immediately with a
run_id (SPEC §8: returns {run_id, status:"running"}). The pipeline is otherwise
synchronous; poll GET /runs/{id} for progress.
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import config
from .db import (
    build_map,
    build_topic_detail,
    domain_page_counts,
    get_connection,
    init_db,
    run_counts,
)
from .pipeline.run import create_run, execute_run

ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    init_db()
    yield


app = FastAPI(title="Topic Coverage", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- schemas ----------------------------------------------------------------

class RunRequest(BaseModel):
    own_domain: str
    competitor_domains: List[str] = Field(default_factory=list)
    market_language: Optional[str] = None
    max_pages_per_domain: Optional[int] = None


# --- background execution ---------------------------------------------------

def _run_in_background(run_id: int) -> None:
    def worker():
        try:
            execute_run(run_id)
        except Exception as exc:  # status is already set to 'error' inside
            print(f"[run {run_id}] failed: {exc}")

    threading.Thread(target=worker, daemon=True).start()


# --- routes -----------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/runs")
def start_run(req: RunRequest):
    lang = req.market_language or config.default_market_language
    # None -> config default; 0 (or negative) -> all pages (bounded by the
    # per-domain crawl time budget); a positive value -> that cap.
    cap = config.max_pages_per_domain if req.max_pages_per_domain is None else req.max_pages_per_domain
    run_id = create_run(req.own_domain, req.competitor_domains, lang, cap)
    _run_in_background(run_id)
    return {"run_id": run_id, "status": "running"}


@app.get("/runs/{run_id}")
def run_status(run_id: int):
    conn = get_connection()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            raise HTTPException(404, "run not found")
        counts = run_counts(conn, run_id)
        domains = domain_page_counts(conn, run_id)
    finally:
        conn.close()
    return {
        "run_id": run_id,
        "status": run["status"],
        "own_domain": run["own_domain"],
        "created_at": run["created_at"],
        "finished_at": run["finished_at"],
        "counts": counts,
        "domains": domains,
    }


@app.get("/runs/{run_id}/map")
def run_map(run_id: int):
    data = build_map(run_id)
    if data is None:
        raise HTTPException(404, "run not found")
    return data


@app.get("/runs/{run_id}/topics/{topic_id}")
def topic_detail(run_id: int, topic_id: int):
    data = build_topic_detail(run_id, topic_id)
    if data is None:
        raise HTTPException(404, "topic not found")
    return data


# --- static frontend (M6) ---------------------------------------------------
# Served last so it doesn't shadow the API routes above.
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
