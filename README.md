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

## Run it on your own computer

You need **Python 3.9+** and **git**. First install takes ~10 min (it downloads
ML libraries); after that it starts in seconds. No API keys, no accounts.

**macOS / Linux**
```bash
git clone https://github.com/growthwithjoseph-bot/topic-coverage.git
cd topic-coverage
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[ml]"
# ⤷ Linux only: if that pulls a multi-GB CUDA torch, cancel and run this first, then re-run:
#   pip install torch --index-url https://download.pytorch.org/whl/cpu

python -m backend.pipeline.demo      # optional: seed a demo run to see it instantly
uvicorn backend.app:app --port 8000
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/growthwithjoseph-bot/topic-coverage.git
cd topic-coverage
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[ml]"
uvicorn backend.app:app --port 8000
```

Then open **http://localhost:8000** → enter your domain + competitor domains
(comma-separated), set **Max pages = 40** for a quick run, click **Analyze**.
Or open **http://localhost:8000/?run=1** first to see the seeded demo instantly.

### Optional: nicer topic names (free, local)
Labels default to keyword-based (readable, e.g. "Health Insurance Benefits").
For plain-English names from a local model, install [Ollama](https://ollama.com),
run `ollama pull qwen2.5:3b`, then create a `.env` file with:
```
TC_LLM_LABELS=true
TC_LLM_PROVIDER=ollama
TC_LLM_MODEL=qwen2.5:3b
```

## How it works (one line)
crawl → extract clean content → chunk + embed → cluster into topics (across all domains) → score each domain's coverage per topic → render the radial map.

## Runs with no API keys
Defaults to local embeddings (`sentence-transformers`) and term-based topic labels, so it works offline. Add an embeddings/LLM provider via `.env` for higher-quality labels (optional).
