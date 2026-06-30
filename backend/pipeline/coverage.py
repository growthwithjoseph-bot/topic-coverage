"""M4 — coverage strength, share, and state (SPEC §6.5–6.6).

For each (domain, topic):
  strength = Σ cosine(chunk, topic centroid) over the domain's chunks *assigned
             to that topic* (cluster membership from M3), normalised per topic so
             the strongest domain ≈ 1.
A domain covers a topic iff it has at least one chunk in that topic's cluster —
this is the discriminating one of the two membership options in §6.5. (Plain
cosine-vs-centroid over all chunks collapses in a tight category, where every
domain's content is near every centroid.) Then per topic we compare the own
domain against competitors to get one of the five coverage states and a share
that sums to 100%.

The state function is a pure deterministic rule (CLAUDE.md hard rule), not a
model. All thresholds come from config.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from ..config import Config, config
from ..db import blob_to_embedding, get_connection


# --- the deterministic state rule (SPEC §6.6, verbatim logic) ---------------

def coverage_state(s_you: float, comp_strengths: List[float], delta: float) -> str:
    s_comp = max(comp_strengths) if comp_strengths else 0.0
    you_covers = s_you > 0
    comp_covers = s_comp > 0
    if you_covers and not comp_covers:
        return "only_you"
    if comp_covers and not you_covers:
        return "only_comp"
    # both cover:
    if s_you > s_comp + delta:
        return "you_lead"
    if s_comp > s_you + delta:
        return "comp_lead"
    return "even"


def coverage_share(s_you: float, comp_strengths: List[float]) -> Tuple[int, int]:
    total = s_you + sum(comp_strengths)
    if total <= 0:
        return 0, 0
    you = int(round(100 * s_you / total))
    return you, 100 - you


# --- data loading -----------------------------------------------------------

def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def _load_assigned_chunks(run_id: int, cfg: Config):
    """Load chunks assigned to a topic, indexed by (topic_id, domain_id).

    Returns (members, domain_ids, is_own) where
      members[(topic_id, domain_id)] = list of (unit_vec, page_id).
    """
    conn = get_connection(cfg.db_path)
    try:
        doms = conn.execute(
            "SELECT id, is_own FROM domains WHERE run_id=?", (run_id,)
        ).fetchall()
        rows = conn.execute(
            "SELECT topic_id, domain_id, page_id, embedding FROM chunks "
            "WHERE run_id=? AND topic_id IS NOT NULL",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()

    is_own = {d["id"]: bool(d["is_own"]) for d in doms}
    domain_ids = [d["id"] for d in doms]
    members: Dict[Tuple[int, int], List[Tuple[np.ndarray, int]]] = {}
    for r in rows:
        v = blob_to_embedding(r["embedding"])
        if v is None:
            continue
        members.setdefault((r["topic_id"], r["domain_id"]), []).append(
            (_normalize(v), r["page_id"])
        )
    return members, domain_ids, is_own


def _load_topics(run_id: int, cfg: Config):
    conn = get_connection(cfg.db_path)
    try:
        rows = conn.execute(
            "SELECT id, centroid FROM topics WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
    finally:
        conn.close()
    return [(r["id"], _normalize(blob_to_embedding(r["centroid"]))) for r in rows]


# --- main -------------------------------------------------------------------

def score_coverage(run_id: int, cfg: Config = config) -> int:
    """Compute and persist per-topic coverage + state. Returns #topics scored."""
    topics = _load_topics(run_id, cfg)
    members, domain_ids, is_own = _load_assigned_chunks(run_id, cfg)
    if not topics:
        return 0

    own_id = next((d for d in domain_ids if is_own.get(d)), None)

    cov_rows = []   # (run_id, topic_id, domain_id, strength, page_count, covered)
    state_rows = []  # (run_id, topic_id, state, you_pct, competitors_pct)

    for topic_id, centroid in topics:
        if centroid is None or centroid.size == 0:
            continue
        raw: Dict[int, float] = {}
        pcount: Dict[int, int] = {}
        for did in domain_ids:
            matched = members.get((topic_id, did), [])
            # weight each assigned chunk by its cosine to the topic centroid
            strength_sum = 0.0
            pages_seen = set()
            for vec, page_id in matched:
                if vec.shape[0] == centroid.shape[0]:
                    strength_sum += max(0.0, float(vec @ centroid))
                pages_seen.add(page_id)
            raw[did] = strength_sum
            pcount[did] = len(pages_seen)

        max_raw = max(raw.values()) if raw else 0.0
        # normalise per topic so the strongest domain ≈ 1 (ratios preserved)
        strength = {d: (raw[d] / max_raw if max_raw > 0 else 0.0) for d in domain_ids}

        for did in domain_ids:
            cov_rows.append(
                (run_id, topic_id, did, strength[did], pcount[did], int(raw[did] > 0))
            )

        s_you = strength.get(own_id, 0.0) if own_id is not None else 0.0
        comp = [strength[d] for d in domain_ids if d != own_id]
        state = coverage_state(s_you, comp, cfg.parity_delta)
        you_pct, comp_pct = coverage_share(s_you, comp)
        state_rows.append((run_id, topic_id, state, you_pct, comp_pct))

    conn = get_connection(cfg.db_path)
    try:
        conn.execute("DELETE FROM topic_coverage WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM topic_state WHERE run_id=?", (run_id,))
        conn.executemany(
            "INSERT INTO topic_coverage "
            "(run_id, topic_id, domain_id, strength, page_count, covered) "
            "VALUES (?,?,?,?,?,?)",
            cov_rows,
        )
        conn.executemany(
            "INSERT INTO topic_state "
            "(run_id, topic_id, state, you_pct, competitors_pct) VALUES (?,?,?,?,?)",
            state_rows,
        )
        conn.commit()
    finally:
        conn.close()
    return len(state_rows)
