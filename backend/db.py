"""SQLite storage for Topic Coverage.

Schema follows SPEC §7. Embeddings are stored as raw float32 blobs and cosine
similarity is done in numpy at read time (fine at this scale — SPEC §7 allows
either this or the sqlite-vec extension).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from .config import config

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    own_domain               TEXT    NOT NULL,
    competitor_domains_json  TEXT    NOT NULL,
    market_language          TEXT    NOT NULL DEFAULT 'en',
    max_pages                INTEGER NOT NULL,
    status                   TEXT    NOT NULL DEFAULT 'pending',
    created_at               TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at              TEXT
);

CREATE TABLE IF NOT EXISTS domains (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    domain    TEXT    NOT NULL,
    is_own    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id   INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    url         TEXT    NOT NULL,
    title       TEXT,
    text        TEXT,
    lang        TEXT,
    etag        TEXT,
    fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id    INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    domain_id  INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    text       TEXT    NOT NULL,
    embedding  BLOB,
    topic_id   INTEGER REFERENCES topics(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    label   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS topics (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    category_id         INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    label               TEXT    NOT NULL,
    centroid            BLOB,
    rep_chunk_ids_json  TEXT
);

CREATE TABLE IF NOT EXISTS topic_coverage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    topic_id    INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    domain_id   INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    strength    REAL    NOT NULL DEFAULT 0,
    page_count  INTEGER NOT NULL DEFAULT 0,
    covered     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS topic_state (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    topic_id         INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    state            TEXT    NOT NULL,
    you_pct          INTEGER NOT NULL DEFAULT 0,
    competitors_pct  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pages_domain   ON pages(domain_id);
CREATE INDEX IF NOT EXISTS idx_chunks_run     ON chunks(run_id);
CREATE INDEX IF NOT EXISTS idx_chunks_domain  ON chunks(domain_id);
CREATE INDEX IF NOT EXISTS idx_chunks_topic   ON chunks(topic_id);
CREATE INDEX IF NOT EXISTS idx_topics_run     ON topics(run_id);
CREATE INDEX IF NOT EXISTS idx_cov_run        ON topic_coverage(run_id);
CREATE INDEX IF NOT EXISTS idx_state_run      ON topic_state(run_id);
"""

# Tables we expect to exist after init — used by the M0 acceptance check.
EXPECTED_TABLES = [
    "runs",
    "domains",
    "pages",
    "chunks",
    "categories",
    "topics",
    "topic_coverage",
    "topic_state",
]


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection with sensible defaults (row access by name, FKs on)."""
    path = Path(db_path) if db_path is not None else config.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path] = None) -> Path:
    """Create the schema if it doesn't exist. Returns the DB path."""
    path = Path(db_path) if db_path is not None else config.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return path


def list_tables(conn: sqlite3.Connection) -> Iterable[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r["name"] for r in rows]


# --- embedding (de)serialisation -------------------------------------------

def embedding_to_blob(vec) -> bytes:
    """Pack a vector to a float32 blob for storage."""
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_embedding(blob: Optional[bytes]) -> Optional[np.ndarray]:
    """Unpack a float32 blob back to a numpy vector (None passes through)."""
    if blob is None:
        return None
    return np.frombuffer(blob, dtype=np.float32)


# --- read helpers for the API (SPEC §8) -------------------------------------

import json as _json
import re as _re


def _snippet(text: str, max_chars: int = 240) -> str:
    """A short representative passage of a chunk (the 'matched sentence')."""
    if not text:
        return ""
    # drop markdown heading lines, collapse whitespace
    body = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    body = _re.sub(r"\s+", " ", body).strip() or text.strip()
    sentences = _re.split(r"(?<=[.!?])\s+", body)
    out = sentences[0] if sentences else body
    if len(out) < 40 and len(sentences) > 1:  # too short -> add the next one
        out = " ".join(sentences[:2])
    return out[:max_chars].strip()


def run_counts(conn: sqlite3.Connection, run_id: int) -> dict:
    def one(sql: str) -> int:
        return conn.execute(sql, (run_id,)).fetchone()[0]

    return {
        "domains": one("SELECT COUNT(*) FROM domains WHERE run_id=?"),
        "pages": one(
            "SELECT COUNT(*) FROM pages WHERE domain_id IN "
            "(SELECT id FROM domains WHERE run_id=?)"
        ),
        "chunks": one("SELECT COUNT(*) FROM chunks WHERE run_id=?"),
        "topics": one("SELECT COUNT(*) FROM topics WHERE run_id=?"),
        "categories": one("SELECT COUNT(*) FROM categories WHERE run_id=?"),
    }


def domain_page_counts(conn: sqlite3.Connection, run_id: int) -> list:
    """Per-domain pages-stored-so-far, own domain first (for live progress)."""
    rows = conn.execute(
        """SELECT d.domain, d.is_own, COUNT(p.id) AS pages
           FROM domains d LEFT JOIN pages p ON p.domain_id = d.id
           WHERE d.run_id = ?
           GROUP BY d.id
           ORDER BY d.is_own DESC, d.id""",
        (run_id,),
    ).fetchall()
    return [
        {"domain": r["domain"], "is_own": bool(r["is_own"]), "pages": r["pages"]}
        for r in rows
    ]


def build_map(run_id: int, db_path: Optional[Path] = None) -> Optional[dict]:
    """Assemble the category→topic tree with states + shares (SPEC §8 /map)."""
    conn = get_connection(db_path)
    try:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if run is None:
            return None
        rows = conn.execute(
            """SELECT cat.id cat_id, cat.label cat_label,
                      t.id topic_id, t.label topic_label,
                      ts.state, ts.you_pct, ts.competitors_pct
               FROM categories cat
               LEFT JOIN topics t ON t.category_id = cat.id
               LEFT JOIN topic_state ts ON ts.topic_id = t.id
               WHERE cat.run_id = ?
               ORDER BY cat.id, t.id""",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    cats: dict = {}
    order: list = []
    for r in rows:
        cid = r["cat_id"]
        if cid not in cats:
            cats[cid] = {"id": cid, "label": r["cat_label"], "topics": []}
            order.append(cid)
        if r["topic_id"] is not None:
            cats[cid]["topics"].append(
                {
                    "id": r["topic_id"],
                    "label": r["topic_label"],
                    "state": r["state"] or "even",
                    "you_pct": r["you_pct"] if r["you_pct"] is not None else 0,
                    "competitors_pct": r["competitors_pct"]
                    if r["competitors_pct"] is not None
                    else 0,
                }
            )

    return {
        "run_id": run_id,
        "status": run["status"],
        "own_domain": run["own_domain"],
        "competitors": _json.loads(run["competitor_domains_json"] or "[]"),
        "categories": [cats[c] for c in order],
    }


def build_topic_detail(
    run_id: int, topic_id: int, db_path: Optional[Path] = None, per_domain: int = 5
) -> Optional[dict]:
    """Per-topic detail + detected content per domain (SPEC §8 /topics/{id})."""
    conn = get_connection(db_path)
    try:
        head = conn.execute(
            """SELECT t.label, c.label category, ts.state, ts.you_pct, ts.competitors_pct
               FROM topics t
               LEFT JOIN categories c ON c.id = t.category_id
               LEFT JOIN topic_state ts ON ts.topic_id = t.id
               WHERE t.id = ? AND t.run_id = ?""",
            (topic_id, run_id),
        ).fetchone()
        if head is None:
            return None
        rows = conn.execute(
            """SELECT d.domain, d.is_own, p.url, p.title, ch.text
               FROM chunks ch
               JOIN pages p ON p.id = ch.page_id
               JOIN domains d ON d.id = ch.domain_id
               WHERE ch.run_id = ? AND ch.topic_id = ?
               ORDER BY d.is_own DESC, d.id""",
            (run_id, topic_id),
        ).fetchall()
    finally:
        conn.close()

    own: list = []
    competitors: list = []
    seen_own = 0
    per_comp: dict = {}
    for r in rows:
        item = {"sentence": _snippet(r["text"]), "url": r["url"], "title": r["title"]}
        if r["is_own"]:
            if seen_own < per_domain:
                own.append(item)
                seen_own += 1
        else:
            dom = r["domain"]
            if per_comp.get(dom, 0) < per_domain:
                competitors.append({"domain": dom, **item})
                per_comp[dom] = per_comp.get(dom, 0) + 1

    return {
        "id": topic_id,
        "label": head["label"],
        "category": head["category"],
        "state": head["state"] or "even",
        "you_pct": head["you_pct"] if head["you_pct"] is not None else 0,
        "competitors_pct": head["competitors_pct"]
        if head["competitors_pct"] is not None
        else 0,
        "detected": {"own": own, "competitors": competitors},
    }


if __name__ == "__main__":  # `python -m backend.db` initialises the DB
    p = init_db()
    print(f"Initialised DB at {p}")
