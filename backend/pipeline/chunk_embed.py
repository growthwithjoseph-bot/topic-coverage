"""M2 — chunk + embed (SPEC §6.4).

Split extracted markdown into ~200–500 token passages (by heading/section,
with slight overlap), embed each chunk, and store the vectors. Embedding
backend is config-switchable: local sentence-transformers by default (no API
key), OpenAI optional. Cosine similarity is done in numpy at read time.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

import numpy as np

from ..config import Config, config
from ..db import blob_to_embedding, embedding_to_blob, get_connection

# Rough words-per-token factor for English prose. We size chunks by word count
# and convert the config's token targets through this factor — precise tokeniser
# counts aren't worth the cost here.
_WORDS_PER_TOKEN = 0.75

_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)


def _est_tokens(text: str) -> int:
    return int(len(text.split()) / _WORDS_PER_TOKEN)


def _split_blocks(text: str) -> List[str]:
    """Split markdown into blocks, keeping headings attached to their section."""
    lines = text.split("\n")
    blocks: List[str] = []
    cur: List[str] = []
    for line in lines:
        if _HEADING_RE.match(line) and cur:
            blocks.append("\n".join(cur).strip())
            cur = [line]
        elif line.strip() == "" and cur:
            blocks.append("\n".join(cur).strip())
            cur = []
        else:
            cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())
    return [b for b in blocks if b]


def _split_long_block(block: str, max_words: int) -> List[str]:
    """Hard-split an oversized block on sentence-ish boundaries by word budget."""
    pieces = re.split(r"(?<=[.!?])\s+", block)
    out, cur, n = [], [], 0
    for s in pieces:
        w = len(s.split())
        if n + w > max_words and cur:
            out.append(" ".join(cur))
            cur, n = [], 0
        cur.append(s)
        n += w
    if cur:
        out.append(" ".join(cur))
    return out


def chunk_text(text: str, cfg: Config = config) -> List[str]:
    """Pack markdown blocks into ~min..max-token chunks with word overlap."""
    if not text:
        return []
    max_words = int(cfg.chunk_max_tokens * _WORDS_PER_TOKEN)
    min_words = int(cfg.chunk_min_tokens * _WORDS_PER_TOKEN)
    overlap_words = int(cfg.chunk_overlap_tokens * _WORDS_PER_TOKEN)

    # Explode blocks, hard-splitting any that exceed the max on their own.
    blocks: List[str] = []
    for b in _split_blocks(text):
        if len(b.split()) > max_words:
            blocks.extend(_split_long_block(b, max_words))
        else:
            blocks.append(b)

    chunks: List[str] = []
    cur: List[str] = []
    cur_words = 0
    for b in blocks:
        bw = len(b.split())
        if cur_words + bw > max_words and cur_words >= min_words:
            chunks.append("\n\n".join(cur))
            # carry an overlap tail into the next chunk
            tail = " ".join("\n\n".join(cur).split()[-overlap_words:]) if overlap_words else ""
            cur = [tail] if tail else []
            cur_words = len(tail.split())
        cur.append(b)
        cur_words += bw
    if cur and cur_words > 0:
        chunks.append("\n\n".join(cur))
    return [c.strip() for c in chunks if c.strip()]


# --- embedding backends -----------------------------------------------------

class _LocalEmbedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name)

    def encode(self, texts: List[str]) -> np.ndarray:
        vecs = self.model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True,  # unit vectors -> cosine = dot product
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)


class _OpenAIEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def encode(self, texts: List[str]) -> np.ndarray:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        vecs = np.asarray([d.embedding for d in resp.data], dtype=np.float32)
        # normalise for cosine-as-dot-product
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vecs / norms


_EMBEDDER = None


def get_embedder(cfg: Config = config):
    """Return a cached embedder for the configured backend."""
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    if cfg.embedding_backend == "openai" and cfg.openai_api_key:
        _EMBEDDER = _OpenAIEmbedder(cfg.openai_api_key)
    else:
        _EMBEDDER = _LocalEmbedder(cfg.local_embedding_model)
    return _EMBEDDER


def embed_texts(texts: List[str], cfg: Config = config) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    return get_embedder(cfg).encode(texts)


# --- run-level: chunk every page, embed, store ------------------------------

def embed_run(run_id: int, cfg: Config = config) -> int:
    """Chunk + embed all pages of a run into the chunks table. Returns count."""
    conn = get_connection(cfg.db_path)
    try:
        pages = conn.execute(
            "SELECT id, domain_id, text FROM pages "
            "WHERE domain_id IN (SELECT id FROM domains WHERE run_id=?)",
            (run_id,),
        ).fetchall()

        records: List[Tuple[int, int, str]] = []  # (page_id, domain_id, chunk_text)
        for pg in pages:
            for ch in chunk_text(pg["text"], cfg):
                records.append((pg["id"], pg["domain_id"], ch))

        if not records:
            return 0

        vectors = embed_texts([r[2] for r in records], cfg)
        rows = [
            (pid, did, txt, embedding_to_blob(vectors[i]), run_id)
            for i, (pid, did, txt) in enumerate(records)
        ]
        conn.executemany(
            "INSERT INTO chunks (page_id, domain_id, text, embedding, run_id) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


# --- cosine neighbour query (M2 acceptance) ---------------------------------

def cosine_neighbors(
    run_id: int, query: str, k: int = 5, cfg: Config = config
) -> List[Tuple[str, float]]:
    """Return the k chunks most cosine-similar to a free-text query."""
    qv = embed_texts([query], cfg)[0]
    conn = get_connection(cfg.db_path)
    try:
        rows = conn.execute(
            "SELECT text, embedding FROM chunks WHERE run_id=?", (run_id,)
        ).fetchall()
    finally:
        conn.close()
    scored: List[Tuple[str, float]] = []
    for r in rows:
        v = blob_to_embedding(r["embedding"])
        if v is None:
            continue
        scored.append((r["text"], float(np.dot(qv, v))))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:k]
