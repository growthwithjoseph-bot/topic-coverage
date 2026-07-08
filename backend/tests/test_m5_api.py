"""M5 API checks. POST /runs is tested with background execution stubbed out
(no live crawl); /map and /topics are tested against a tiny hand-seeded run."""
import numpy as np
from fastapi.testclient import TestClient

from backend import app as app_module
from backend.config import config
from backend.db import embedding_to_blob, get_connection, init_db

client = TestClient(app_module.app)


def _seed_run() -> int:
    init_db(config.db_path)
    conn = get_connection(config.db_path)
    try:
        run_id = conn.execute(
            "INSERT INTO runs (own_domain, competitor_domains_json, market_language, "
            "max_pages, status) VALUES (?,?,?,?, 'done')",
            ("you.com", '["rival.com"]', "en", 50),
        ).lastrowid
        own = conn.execute(
            "INSERT INTO domains (run_id, domain, is_own) VALUES (?,?,1)", (run_id, "you.com")
        ).lastrowid
        comp = conn.execute(
            "INSERT INTO domains (run_id, domain, is_own) VALUES (?,?,0)", (run_id, "rival.com")
        ).lastrowid
        cat = conn.execute(
            "INSERT INTO categories (run_id, label) VALUES (?,?)", (run_id, "Planning")
        ).lastrowid
        cen = embedding_to_blob(np.array([1.0, 0.0], dtype=np.float32))
        topic = conn.execute(
            "INSERT INTO topics (run_id, category_id, label, centroid) VALUES (?,?,?,?)",
            (run_id, cat, "Gantt Charts", cen),
        ).lastrowid
        conn.execute(
            "INSERT INTO topic_state (run_id, topic_id, state, you_pct, competitors_pct) "
            "VALUES (?,?,?,?,?)",
            (run_id, topic, "you_lead", 60, 40),
        )
        op = conn.execute(
            "INSERT INTO pages (domain_id, url, title, text, lang) VALUES (?,?,?,?,?)",
            (own, "https://you.com/gantt", "Gantt Guide", "Gantt charts plan timelines.", "en"),
        ).lastrowid
        cp = conn.execute(
            "INSERT INTO pages (domain_id, url, title, text, lang) VALUES (?,?,?,?,?)",
            (comp, "https://rival.com/gantt", "Rival Gantt", "Rival gantt timeline view.", "en"),
        ).lastrowid
        v = embedding_to_blob(np.array([1.0, 0.0], dtype=np.float32))
        conn.execute(
            "INSERT INTO chunks (page_id, domain_id, run_id, text, embedding, topic_id) "
            "VALUES (?,?,?,?,?,?)",
            (op, own, run_id, "Gantt charts plan project timelines and milestones.", v, topic),
        )
        conn.execute(
            "INSERT INTO chunks (page_id, domain_id, run_id, text, embedding, topic_id) "
            "VALUES (?,?,?,?,?,?)",
            (cp, comp, run_id, "Rival gantt timeline view for scheduling.", v, topic),
        )
        conn.commit()
        return run_id, topic
    finally:
        conn.close()


def test_post_runs_returns_running(monkeypatch):
    monkeypatch.setattr(app_module, "_run_in_background", lambda run_id: None)
    resp = client.post("/runs", json={"own_domain": "you.com", "competitor_domains": ["rival.com"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running" and isinstance(body["run_id"], int)


def test_map_and_topic_detail():
    run_id, topic = _seed_run()

    m = client.get(f"/runs/{run_id}/map").json()
    assert m["own_domain"] == "you.com"
    assert m["competitors"] == ["rival.com"]
    assert m["categories"][0]["label"] == "Planning"
    t = m["categories"][0]["topics"][0]
    assert t["state"] == "you_lead" and t["you_pct"] == 60 and t["competitors_pct"] == 40

    d = client.get(f"/runs/{run_id}/topics/{topic}").json()
    assert d["label"] == "Gantt Charts" and d["category"] == "Planning"
    assert d["detected"]["own"] and "gantt" in d["detected"]["own"][0]["sentence"].lower()
    assert d["detected"]["own"][0]["url"] == "https://you.com/gantt"
    assert d["detected"]["competitors"][0]["domain"] == "rival.com"


def test_missing_run_404():
    assert client.get("/runs/999999/map").status_code == 404


def test_pages_endpoint_lists_scraped_pages():
    run_id, _ = _seed_run()
    resp = client.get(f"/runs/{run_id}/pages")
    assert resp.status_code == 200
    doms = {d["domain"]: d for d in resp.json()["domains"]}
    assert doms["you.com"]["is_own"] is True
    assert len(doms["you.com"]["pages"]) == 1
    assert doms["you.com"]["pages"][0]["url"].startswith("http")
    assert client.get("/runs/999999/pages").status_code == 404


def test_status_includes_per_domain_page_counts():
    run_id, _ = _seed_run()
    info = client.get(f"/runs/{run_id}").json()
    doms = {d["domain"]: d for d in info["domains"]}
    assert doms["you.com"]["is_own"] is True
    assert doms["you.com"]["pages"] == 1 and doms["rival.com"]["pages"] == 1
    # own domain is listed first
    assert info["domains"][0]["is_own"] is True


def test_post_runs_zero_means_all_pages(monkeypatch):
    captured = {}
    monkeypatch.setattr(app_module, "_run_in_background", lambda rid: captured.update(rid=rid))
    resp = client.post("/runs", json={"own_domain": "you.com", "max_pages_per_domain": 0})
    assert resp.status_code == 200
    conn = get_connection(config.db_path)
    try:
        cap = conn.execute(
            "SELECT max_pages FROM runs WHERE id=?", (resp.json()["run_id"],)
        ).fetchone()[0]
    finally:
        conn.close()
    assert cap == 0  # 0 is preserved -> discovery treats it as "all pages"
