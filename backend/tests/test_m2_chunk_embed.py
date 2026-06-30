"""M2 checks. Chunking is tested offline. The embed→store→cosine path is tested
with a deterministic fake embedder (monkeypatched) so it needs no model
download; a live cosine sanity check runs via scripts during milestone review."""
from pathlib import Path

import numpy as np

from backend.config import Config
from backend.db import get_connection, init_db
from backend.pipeline import chunk_embed
from backend.pipeline.run import create_run, get_domains


def test_chunk_sizes_within_band():
    cfg = Config()
    # ~900 words of repeated prose -> several chunks, none wildly oversized.
    text = "\n\n".join(
        [" ".join(["topic coverage analysis sentence number %d" % i] * 20) for i in range(12)]
    )
    chunks = chunk_text = chunk_embed.chunk_text(text, cfg)
    assert len(chunks) >= 2
    max_words = int(cfg.chunk_max_tokens * 0.75)
    for c in chunks:
        # allow a little slack for the overlap tail
        assert len(c.split()) <= max_words + int(cfg.chunk_overlap_tokens * 0.75) + 5


def _fake_encode(texts):
    """Map each text to a tiny deterministic unit vector by keyword."""
    vocab = ["gantt", "api", "webhook", "mobile"]
    out = []
    for t in texts:
        tl = t.lower()
        v = np.array([tl.count(w) for w in vocab], dtype=np.float32) + 0.01
        v /= np.linalg.norm(v)
        out.append(v)
    return np.asarray(out, dtype=np.float32)


def test_embed_store_and_cosine(tmp_path: Path, monkeypatch):
    cfg = Config(db_path=tmp_path / "m2.db")
    init_db(cfg.db_path)
    run_id = create_run("example.com", [], "en", 50, cfg=cfg)
    dom = get_domains(run_id, cfg=cfg)[0]

    conn = get_connection(cfg.db_path)
    try:
        for txt in [
            "Gantt charts and gantt timelines for planning. " * 30,
            "Public API and webhook integrations for developers. " * 30,
            "Mobile app on the go productivity. " * 30,
        ]:
            conn.execute(
                "INSERT INTO pages (domain_id, url, title, text, lang) VALUES (?,?,?,?,?)",
                (dom["id"], "https://example.com/" + txt[:8], "t", txt, "en"),
            )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(chunk_embed, "embed_texts", lambda texts, cfg=cfg: _fake_encode(texts))

    n = chunk_embed.embed_run(run_id, cfg=cfg)
    assert n >= 3

    hits = chunk_embed.cosine_neighbors(run_id, "gantt chart timeline", k=1, cfg=cfg)
    assert hits and "gantt" in hits[0][0].lower()
