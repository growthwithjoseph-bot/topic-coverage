"""M3 checks. Pure helpers + the small-data fallback path are tested offline
(no BERTopic run); full clustering is verified live during milestone review."""
from pathlib import Path

import numpy as np

from backend.config import Config
from backend.db import get_connection, init_db
from backend.pipeline import topics
from backend.pipeline.run import create_run, get_domains


def test_terms_to_label_normalises_readably():
    # dedupes overlapping words and prefers the multi-word phrase
    assert topics._terms_to_label(["vs", "vs code", "code", "environment"]) == "VS Code Environment"
    # acronyms uppercased, plurals deduped
    assert topics._terms_to_label(["llms", "customer", "llm"]) == "LLMs Customer"
    assert topics._terms_to_label(["api", "public api", "webhooks"]) == "Public API Webhooks"
    # no '·' soup, Title-Cased
    label = topics._terms_to_label(["insurance", "health", "benefits", "health insurance"])
    assert "·" not in label and label[0].isupper()
    assert topics._terms_to_label([]) == "Topic"


def test_category_count_respects_band():
    cfg = Config()
    assert topics._category_count(1, cfg) == 1
    assert topics._category_count(30, cfg) == 10            # round(30/3)=10 in [8,14]
    assert topics._category_count(60, cfg) == cfg.num_categories_max
    assert topics._category_count(5, cfg) <= 5


def test_reassign_noise_uses_floor():
    cents = {0: np.array([1.0, 0.0], dtype=np.float32)}
    embs = np.array([[0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    out = topics._reassign_noise([-1, -1], embs, cents, floor=0.5)
    assert out[0] == 0       # close to centroid -> reassigned
    assert out[1] == -1      # orthogonal, below floor -> stays noise


def test_discover_topics_small_data_fallback(tmp_path: Path):
    """Few chunks -> single 'fallback' topic, every chunk tagged, 1 category."""
    cfg = Config(db_path=tmp_path / "m3.db")
    init_db(cfg.db_path)
    run_id = create_run("example.com", [], "en", 50, cfg=cfg)
    dom = get_domains(run_id, cfg=cfg)[0]

    conn = get_connection(cfg.db_path)
    try:
        page = conn.execute(
            "INSERT INTO pages (domain_id, url, text, lang) VALUES (?,?,?,?)",
            (dom["id"], "https://example.com/p", "x", "en"),
        ).lastrowid
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32).tobytes()
        for i in range(3):
            conn.execute(
                "INSERT INTO chunks (page_id, domain_id, run_id, text, embedding) "
                "VALUES (?,?,?,?,?)",
                (page, dom["id"], run_id, f"gantt chart planning text {i}", v),
            )
        conn.commit()
    finally:
        conn.close()

    n_topics, n_cats = topics.discover_topics(run_id, cfg=cfg)
    assert n_topics == 1 and n_cats == 1

    conn = get_connection(cfg.db_path)
    try:
        untagged = conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE run_id=? AND topic_id IS NULL", (run_id,)
        ).fetchone()["c"]
        label = conn.execute(
            "SELECT label FROM topics WHERE run_id=?", (run_id,)
        ).fetchone()["label"]
    finally:
        conn.close()
    assert untagged == 0
    assert label and label != "Topic"
