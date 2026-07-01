"""M3 — topic discovery (SPEC §6.4).

Cluster ALL chunks (every domain together, so topics are shared vocabulary for
comparison) into topics with BERTopic (sentence-transformers → UMAP → HDBSCAN →
c-TF-IDF). Then:
  - drop / reassign the HDBSCAN noise cluster (-1) above a similarity floor,
  - label each topic from its top c-TF-IDF terms (LLM labels optional, off by
    default so the repo runs with no API key),
  - group topic centroids into ~8–14 categories (agglomerative clustering).

All granularity knobs (min_cluster_size, n_neighbors, category counts, the
reassignment floor) come from config.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..config import Config, config
from ..db import blob_to_embedding, embedding_to_blob, get_connection

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'+/-]{1,}")


# --- helpers ----------------------------------------------------------------

def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


# Tokens that should render uppercase rather than Title Case.
_ACRONYMS = {
    "api", "ai", "llm", "ui", "ux", "seo", "css", "html", "sql", "rest",
    "oauth", "sdk", "crm", "saas", "faq", "ios", "kpi", "roi", "b2b", "b2c",
    "url", "http", "https", "vs", "ci", "cd", "ml", "gpu", "cpu", "pdf", "csv",
}
# Filler words not worth keeping in a short label.
_LABEL_STOP = {
    "the", "and", "for", "with", "your", "you", "our", "their", "this", "that",
    "from", "into", "are", "was", "how", "what", "why", "can", "will", "get",
    "use", "using", "based", "guide", "part", "more", "new", "best",
}


def _lemma(w: str) -> str:
    """Crude singular form so 'llm'/'llms' and 'team'/'teams' dedupe."""
    w = w.lower()
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def _cap(word: str) -> str:
    lw = word.lower()
    if lw in _ACRONYMS:
        return lw.upper()
    if lw.endswith("s") and lw[:-1] in _ACRONYMS:  # pluralised acronym: LLMs, APIs
        return lw[:-1].upper() + "s"
    return word if not word.islower() else word[:1].upper() + word[1:]


def _terms_to_label(terms: List[str], k: int = 3) -> str:
    """Build a readable phrase from ranked c-TF-IDF terms.

    Prefers the top multi-word phrase (e.g. 'health insurance'), then fills in
    distinct extra words, deduping overlapping/plural words. Acronyms are
    uppercased and the result is Title-Cased — no keyword-soup '·' joins.
    e.g. ['vs','vs code','code','environment'] -> 'VS Code Environment'.
    """
    cleaned = [t.strip() for t in terms if t and t.strip()]
    if not cleaned:
        return "Topic"

    words: List[str] = []          # ordered, kept words (original case)
    used = set()                   # lemmas already represented

    def add_word(w: str) -> None:
        lem = _lemma(w)
        if lem in used or w.lower() in _LABEL_STOP or len(w) < 2:
            return
        used.add(lem)
        words.append(w)

    # 1) seed with the first informative multi-word term (most specific)
    for t in cleaned:
        parts = t.split()
        if len(parts) >= 2 and any(p.lower() not in _LABEL_STOP for p in parts):
            for p in parts:
                add_word(p)
            break

    # 2) fill with remaining terms' words in importance order
    for t in cleaned:
        for p in t.split():
            add_word(p)
            if len(words) >= k:
                break
        if len(words) >= k:
            break

    if not words:
        return "Topic"
    return " ".join(_cap(w) for w in words[:k])


# --- optional LLM labelling (Anthropic) -------------------------------------
# Off by default. Activates only when cfg.llm_labels AND an API key is present;
# any failure falls back silently to the term-based labels above, so the repo
# always runs with no keys.

_LLM_LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "label": {"type": "string"},
                },
                "required": ["index", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["labels"],
    "additionalProperties": False,
}


def _llm_enabled(cfg: Config) -> bool:
    if not cfg.llm_labels:
        return False
    provider = (cfg.llm_provider or "anthropic").lower()
    if provider == "ollama":
        return True  # local model, no key required (fails soft if not running)
    return bool(os.getenv("ANTHROPIC_API_KEY") or cfg.anthropic_api_key)


def _parse_label_json(text: str) -> Dict[int, str]:
    data = json.loads(text)
    out: Dict[int, str] = {}
    for item in data.get("labels", []):
        label = (item.get("label") or "").strip()
        if label:
            out[int(item["index"])] = label
    return out


def _llm_labels(prompt: str, cfg: Config) -> Dict[int, str]:
    """One structured-output call -> {index: label}. {} on any failure."""
    provider = (cfg.llm_provider or "anthropic").lower()
    if provider == "ollama":
        return _llm_labels_ollama(prompt, cfg)
    return _llm_labels_anthropic(prompt, cfg)


def _llm_labels_anthropic(prompt: str, cfg: Config) -> Dict[int, str]:
    try:
        import anthropic

        client = anthropic.Anthropic()
        resp = client.messages.create(
            model=cfg.llm_model,
            max_tokens=2048,
            output_config={"format": {"type": "json_schema", "schema": _LLM_LABEL_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return _parse_label_json(text)
    except Exception:
        return {}


def _llm_labels_ollama(prompt: str, cfg: Config) -> Dict[int, str]:
    """Local labelling via Ollama's HTTP API (free, no key). Uses structured
    output (`format` schema) so the model returns valid JSON."""
    try:
        import httpx

        # Guard against an Anthropic model id being left in TC_LLM_MODEL.
        model = cfg.llm_model
        if not model or model.startswith("claude"):
            model = "qwen2.5:3b"
        url = cfg.ollama_host.rstrip("/") + "/api/chat"
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": _LLM_LABEL_SCHEMA,  # Ollama structured outputs (>=0.5)
            "options": {"temperature": 0},
        }
        resp = httpx.post(url, json=body, timeout=120.0)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return _parse_label_json(content)
    except Exception:
        return {}


def _llm_label_topics(topic_objs: List[dict], cfg: Config) -> Dict[int, str]:
    blocks = []
    for i, t in enumerate(topic_objs):
        terms = ", ".join(t["terms"][:8])
        sample = (t.get("sample") or "").replace("\n", " ")[:300]
        blocks.append(f"{i}. terms: {terms}\n   sample: {sample}")
    prompt = (
        "These are content clusters discovered from crawling websites. For each "
        "numbered cluster, give a concise, human-readable topic label of 2-4 words "
        "in Title Case (e.g. 'Gantt Charts', 'Public API & Webhooks', 'Health "
        "Insurance'). Base it on the key terms and the sample text. Return exactly "
        "one label per index.\n\n" + "\n\n".join(blocks)
    )
    return _llm_labels(prompt, cfg)


def _llm_label_categories(cat_to_labels: Dict[int, List[str]], cfg: Config) -> Dict[int, str]:
    keys = sorted(cat_to_labels.keys())
    blocks = [f"{n}. topics: {', '.join(cat_to_labels[k][:12])}" for n, k in enumerate(keys)]
    prompt = (
        "Each numbered group below is a set of related content topics. Give each "
        "group a short category name of 1-3 words in Title Case that captures the "
        "common theme (e.g. 'Planning & Scheduling', 'Integrations', 'AI "
        "Features'). Return exactly one name per index.\n\n" + "\n".join(blocks)
    )
    by_index = _llm_labels(prompt, cfg)
    return {keys[i]: lab for i, lab in by_index.items() if 0 <= i < len(keys)}


def _load_chunks(run_id: int, cfg: Config):
    conn = get_connection(cfg.db_path)
    try:
        rows = conn.execute(
            "SELECT id, text, embedding FROM chunks WHERE run_id=? ORDER BY id",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    ids, docs, embs = [], [], []
    for r in rows:
        v = blob_to_embedding(r["embedding"])
        if v is None:
            continue
        ids.append(r["id"])
        docs.append(r["text"])
        embs.append(v)
    embeddings = np.vstack(embs) if embs else np.zeros((0, 0), dtype=np.float32)
    return ids, docs, embeddings


# --- BERTopic clustering ----------------------------------------------------

def _cluster(docs: List[str], embeddings: np.ndarray, cfg: Config):
    """Run BERTopic on precomputed embeddings. Returns (labels, top_terms_by_label).

    labels: list[int] cluster id per doc (-1 = noise).
    top_terms_by_label: {cluster_id: [term, ...]}.
    Falls back to a single cluster when there's too little data to cluster.
    """
    n = len(docs)
    # Too few documents to cluster meaningfully -> one topic.
    if n < max(4, cfg.min_cluster_size):
        return [0] * n, {0: _fallback_terms(docs)}

    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    n_neighbors = max(2, min(cfg.umap_n_neighbors, n - 1))
    n_components = max(2, min(5, n - 2))
    min_cluster = max(2, min(cfg.min_cluster_size, n // 2))

    umap_model = UMAP(
        n_neighbors=n_neighbors,
        n_components=n_components,
        min_dist=0.0,
        metric="cosine",
        random_state=42,
    )
    hdbscan_model = HDBSCAN(
        min_cluster_size=min_cluster,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    vectorizer = CountVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1)

    topic_model = BERTopic(
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        vectorizer_model=vectorizer,
        calculate_probabilities=False,
        verbose=False,
    )
    labels, _ = topic_model.fit_transform(docs, embeddings)
    labels = [int(x) for x in labels]

    # If everything collapsed to noise, fall back to a single topic.
    if all(l == -1 for l in labels):
        return [0] * n, {0: _fallback_terms(docs)}

    top_terms: Dict[int, List[str]] = {}
    for cid in set(labels):
        if cid == -1:
            continue
        terms = [w for w, _ in (topic_model.get_topic(cid) or []) if w]
        top_terms[cid] = terms or _fallback_terms([docs[i] for i in range(n) if labels[i] == cid])
    return labels, top_terms


def _fallback_terms(docs: List[str], k: int = 5) -> List[str]:
    """Cheap top-term extraction when c-TF-IDF isn't available."""
    from collections import Counter

    try:
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS as STOP
    except Exception:
        STOP = set()
    counts: Counter = Counter()
    for d in docs:
        for w in _WORD_RE.findall(d.lower()):
            if w not in STOP and len(w) > 2:
                counts[w] += 1
    return [w for w, _ in counts.most_common(k)] or ["topic"]


# --- noise reassignment -----------------------------------------------------

def _reassign_noise(
    labels: List[int],
    embeddings: np.ndarray,
    centroids: Dict[int, np.ndarray],
    floor: float,
) -> List[int]:
    """Reassign -1 chunks to the nearest topic centroid above `floor`."""
    if not centroids:
        return labels
    cids = list(centroids.keys())
    mat = np.vstack([centroids[c] for c in cids])
    out = list(labels)
    for i, l in enumerate(labels):
        if l != -1:
            continue
        sims = mat @ _normalize(embeddings[i])
        j = int(np.argmax(sims))
        if float(sims[j]) >= floor:
            out[i] = cids[j]
    return out


# --- categories -------------------------------------------------------------

def _category_count(n_topics: int, cfg: Config) -> int:
    if n_topics <= 1:
        return 1
    k = max(1, round(n_topics / 3))
    if n_topics >= cfg.num_categories_min:
        k = max(cfg.num_categories_min, min(cfg.num_categories_max, k))
    return min(k, n_topics)


def _group_categories(
    topic_centroids: List[np.ndarray], cfg: Config
) -> List[int]:
    """Cluster topic centroids into category indices."""
    n = len(topic_centroids)
    k = _category_count(n, cfg)
    if k <= 1 or n <= 1:
        return [0] * n
    from sklearn.cluster import AgglomerativeClustering

    mat = np.vstack(topic_centroids)
    model = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average")
    return [int(x) for x in model.fit_predict(mat)]


# --- main -------------------------------------------------------------------

def discover_topics(run_id: int, cfg: Config = config) -> Tuple[int, int]:
    """Cluster a run's chunks into topics + categories, persist, tag chunks.

    Returns (n_topics, n_categories).
    """
    ids, docs, embeddings = _load_chunks(run_id, cfg)
    if not ids:
        return 0, 0

    labels, top_terms = _cluster(docs, embeddings, cfg)

    # Per-cluster centroids over member chunks (unit vectors).
    centroids: Dict[int, np.ndarray] = {}
    for cid in set(labels):
        if cid == -1:
            continue
        members = [i for i, l in enumerate(labels) if l == cid]
        centroids[cid] = _normalize(embeddings[members].mean(axis=0))

    labels = _reassign_noise(labels, embeddings, centroids, cfg.sim_threshold)

    # Final topic set (clusters with at least one member after reassignment).
    cluster_ids = sorted({l for l in labels if l != -1})
    if not cluster_ids:  # safety: keep everything as one topic
        cluster_ids = [0]
        labels = [0] * len(labels)
        centroids = {0: _normalize(embeddings.mean(axis=0))}
        top_terms = {0: _fallback_terms(docs)}

    topic_objs = []
    for cid in cluster_ids:
        members = [i for i, l in enumerate(labels) if l == cid]
        centroid = _normalize(embeddings[members].mean(axis=0))
        # representative chunks: members closest to the centroid
        sims = [(float(centroid @ _normalize(embeddings[i])), ids[i]) for i in members]
        sims.sort(reverse=True)
        rep_ids = [cid_ for _, cid_ in sims[:3]]
        terms = top_terms.get(cid) or _fallback_terms([docs[i] for i in members])
        id_to_doc = {ids[i]: docs[i] for i in members}
        sample = " ".join(id_to_doc.get(r, "") for r in rep_ids[:2])
        topic_objs.append(
            {
                "label": _terms_to_label(terms),
                "terms": terms,
                "sample": sample,
                "centroid": centroid,
                "member_chunk_ids": [ids[i] for i in members],
                "rep_chunk_ids": rep_ids,
            }
        )

    # Optional: replace term-based topic labels with LLM-generated ones.
    if _llm_enabled(cfg):
        for i, lab in _llm_label_topics(topic_objs, cfg).items():
            if 0 <= i < len(topic_objs):
                topic_objs[i]["label"] = lab

    cat_idx = _group_categories([t["centroid"] for t in topic_objs], cfg)

    # Category labels from member topics' terms (LLM-upgraded if enabled).
    cat_terms: Dict[int, List[str]] = {}
    cat_member_labels: Dict[int, List[str]] = {}
    for t, ci in zip(topic_objs, cat_idx):
        cat_terms.setdefault(ci, []).extend(t["terms"][:3])
        cat_member_labels.setdefault(ci, []).append(t["label"])
    cat_labels = {ci: _terms_to_label(terms, k=2) for ci, terms in cat_terms.items()}
    if _llm_enabled(cfg):
        for ci, lab in _llm_label_categories(cat_member_labels, cfg).items():
            cat_labels[ci] = lab

    _persist(run_id, topic_objs, cat_idx, cat_labels, cfg)
    return len(topic_objs), len(set(cat_idx))


def _persist(run_id, topic_objs, cat_idx, cat_labels, cfg: Config) -> None:
    conn = get_connection(cfg.db_path)
    try:
        # clear any prior topic discovery for idempotent re-runs
        conn.execute("UPDATE chunks SET topic_id=NULL WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM topics WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM categories WHERE run_id=?", (run_id,))

        # insert categories, map index -> db id
        cat_db: Dict[int, int] = {}
        for ci in sorted(set(cat_idx)):
            cur = conn.execute(
                "INSERT INTO categories (run_id, label) VALUES (?, ?)",
                (run_id, cat_labels.get(ci, "Category")),
            )
            cat_db[ci] = cur.lastrowid

        # insert topics, tag member chunks
        for t, ci in zip(topic_objs, cat_idx):
            cur = conn.execute(
                "INSERT INTO topics (run_id, category_id, label, centroid, rep_chunk_ids_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    cat_db[ci],
                    t["label"],
                    embedding_to_blob(t["centroid"]),
                    json.dumps(t["rep_chunk_ids"]),
                ),
            )
            topic_db_id = cur.lastrowid
            conn.executemany(
                "UPDATE chunks SET topic_id=? WHERE id=?",
                [(topic_db_id, cid) for cid in t["member_chunk_ids"]],
            )
        conn.commit()
    finally:
        conn.close()
