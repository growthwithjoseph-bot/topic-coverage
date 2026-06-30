"""M4 checks. The deterministic state/share rule (SPEC §6.6) is exhaustively
unit-tested; score_coverage is tested end-to-end on hand-built embeddings that
force known coverage states."""
from pathlib import Path

import numpy as np

from backend.config import Config
from backend.db import embedding_to_blob, get_connection, init_db
from backend.pipeline.coverage import coverage_share, coverage_state, score_coverage
from backend.pipeline.run import create_run, get_domains


D = 0.10  # delta


def test_state_only_you_and_only_comp():
    assert coverage_state(0.8, [0.0], D) == "only_you"
    assert coverage_state(0.0, [0.5], D) == "only_comp"
    assert coverage_state(0.5, [], D) == "only_you"


def test_state_lead_and_even_respect_delta():
    assert coverage_state(0.9, [0.5], D) == "you_lead"
    assert coverage_state(0.5, [0.9], D) == "comp_lead"
    assert coverage_state(0.50, [0.45], D) == "even"      # within band
    assert coverage_state(0.61, [0.50], D) == "you_lead"  # just outside band
    assert coverage_state(0.60, [0.50], D) == "even"      # exactly delta -> not a lead


def test_state_picks_strongest_competitor():
    assert coverage_state(0.55, [0.30, 0.90, 0.20], D) == "comp_lead"


def test_share_sums_to_100():
    assert coverage_share(1.0, [0.0]) == (100, 0)
    assert coverage_share(0.0, [1.0]) == (0, 100)
    y, c = coverage_share(0.6, [0.2, 0.2])
    assert y + c == 100 and y == 60


def _seed_topic_run(cfg: Config):
    """One topic with centroid e0; own + 2 competitors with crafted chunks."""
    init_db(cfg.db_path)
    run_id = create_run("you.com", ["a.com", "b.com"], "en", 50, cfg=cfg)
    doms = get_domains(run_id, cfg=cfg)  # own first
    own, a, b = doms[0]["id"], doms[1]["id"], doms[2]["id"]

    e0 = np.array([1.0, 0.0, 0.0], dtype=np.float32)  # topic direction
    near = np.array([0.98, 0.20, 0.0], dtype=np.float32)
    near /= np.linalg.norm(near)
    far = np.array([0.0, 1.0, 0.0], dtype=np.float32)  # below threshold

    conn = get_connection(cfg.db_path)
    try:
        cat = conn.execute(
            "INSERT INTO categories (run_id,label) VALUES (?,?)", (run_id, "Cat")
        ).lastrowid
        topic = conn.execute(
            "INSERT INTO topics (run_id,category_id,label,centroid) VALUES (?,?,?,?)",
            (run_id, cat, "Topic", embedding_to_blob(e0)),
        ).lastrowid

        def add(domain_id, vec, n, assigned):
            # assigned=topic id when the chunk is a member of the topic cluster,
            # or None when it landed elsewhere (so the domain doesn't cover it).
            page = conn.execute(
                "INSERT INTO pages (domain_id,url,text,lang) VALUES (?,?,?,?)",
                (domain_id, f"https://d/{domain_id}", "x", "en"),
            ).lastrowid
            for _ in range(n):
                conn.execute(
                    "INSERT INTO chunks (page_id,domain_id,run_id,text,embedding,topic_id) "
                    "VALUES (?,?,?,?,?,?)",
                    (page, domain_id, run_id, "t", embedding_to_blob(vec), assigned),
                )

        add(own, near, 5, topic)   # own strongly covers (5 member chunks)
        add(a, near, 1, topic)     # competitor a weakly covers (1 member chunk)
        add(b, far, 2, None)       # competitor b: not assigned -> doesn't cover
        conn.commit()
    finally:
        conn.close()
    return run_id, topic


def test_score_coverage_end_to_end(tmp_path: Path):
    cfg = Config(db_path=tmp_path / "m4.db")
    run_id, topic = _seed_topic_run(cfg)
    n = score_coverage(run_id, cfg=cfg)
    assert n == 1

    conn = get_connection(cfg.db_path)
    try:
        state = conn.execute(
            "SELECT state, you_pct, competitors_pct FROM topic_state WHERE topic_id=?",
            (topic,),
        ).fetchone()
        cov = conn.execute(
            "SELECT domain_id, strength, covered FROM topic_coverage WHERE topic_id=?",
            (topic,),
        ).fetchall()
    finally:
        conn.close()

    # own covers far more than the strongest competitor -> you_lead
    assert state["state"] == "you_lead"
    assert state["you_pct"] + state["competitors_pct"] == 100
    # strongest domain normalised to 1.0; the 'far' competitor covered=0
    strengths = {r["domain_id"]: r["strength"] for r in cov}
    assert abs(max(strengths.values()) - 1.0) < 1e-6
    assert any(r["covered"] == 0 for r in cov)
