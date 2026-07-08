---
title: Topic Coverage
emoji: 🕸️
colorFrom: green
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Topic Coverage

Crawl a brand's site and its competitors', discover the topics each writes about, and see — as a radial map — **who covers what, and who covers it more**. A pure content-coverage comparison (no demand, no authority).

> The block above is Hugging Face Spaces metadata (ignored by GitHub). Deploy: push this repo to a **Docker** Space; it serves the app on port 7860.

See **`SPEC.md`** for the full build specification and **`CLAUDE.md`** for working conventions.

## Quickstart (target state once built)

```bash
# 1. install
make install            # or: pip install -e .  &&  playwright install chromium

# 2. run the API
make dev                # FastAPI on http://localhost:8000

# 3. start an analysis
curl -X POST localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"own_domain":"asana.com","competitor_domains":["monday.com","clickup.com","notion.so"]}'

# 4. open the UI
open http://localhost:8000/?run=1   # radial coverage map, served by the API
```

The pipeline needs the ML stack for embeddings + topic discovery:

```bash
make install        # core deps (crawl + extract + API)
make install-ml     # sentence-transformers + BERTopic stack (M2–M3)
```

### Try it offline (no crawl, no keys)

```bash
python -m backend.pipeline.demo   # seeds a reproducible 4-domain run
make dev                          # then open http://localhost:8000/?run=1
```

The demo seeds crawled-equivalent content for one own domain + three
competitors; topics are still **discovered by clustering** that content (not
hardcoded), so it exercises the full embed → topics → coverage → map path
without hitting the network.

## How it works (one line)
crawl → extract clean content → chunk + embed → cluster into topics (across all domains) → score each domain's coverage per topic → render the radial map.

## Runs with no API keys
Defaults to local embeddings (`sentence-transformers`) and term-based topic labels, so it works offline. Add an embeddings/LLM provider via `.env` for higher-quality labels (optional).
