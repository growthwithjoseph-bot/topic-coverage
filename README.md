---
title: Topic Coverage
emoji: 🕸️
colorFrom: green
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# 🕸️ Topic Coverage

### Know exactly where you win — and where you're invisible — in the content battle for your market.

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Runs 100% local](https://img.shields.io/badge/runs-100%25%20local-15803d)
![No API keys](https://img.shields.io/badge/API%20keys-none%20required-22c55e)
![Local AI](https://img.shields.io/badge/AI-on--device%20embeddings-6366f1)

Type in **your domain + your competitors'**. Topic Coverage crawls every site,
reads all the copy, and clusters it into the **topics your category actually talks
about**. Then it draws one picture: a **radial map** showing, topic by topic,
**who covers what — and who covers it more.**

---

## 💡 Why it matters (the business value)

Content and SEO teams burn budget writing *more* without knowing **where more
actually helps**. "We should do more content" is a guess. Topic Coverage turns it
into an **evidence-backed map**:

| Without it 😵‍💫 | With Topic Coverage ✅ |
|---|---|
| "Are we behind on content?" — a gut feeling | A ranked, visual answer per topic |
| Competitor research done by hand, tab by tab | Every competitor's whole site, clustered automatically |
| Content plans based on opinion | Plans based on **where you measurably lead or lag** |
| No way to prove content ROI to leadership | A shareable map that makes the gap obvious |

**In one glance you can see:**
- 🟢 **Topics you own** — your moat; defend and double down
- 🔴 **Topics only competitors cover** — you're invisible here; biggest blind spots
- 🟠 **Topics where a competitor out-covers you** — you're losing ground
- ⚪ **Even topics** — contested; winnable with focused effort

**Who it's for:** 📈 content & SEO leads · 🚀 founders sizing up a market · 🏢
agencies auditing a client vs. its rivals · 🧭 product marketers shaping positioning.

> **Honest scope:** this compares *content that exists* — who has written what, and
> how much. It is **not** an SEO-rankings or backlink tool (that's a separate,
> bigger beast). It's the fastest way to see the shape of the content battlefield.

---

## ✨ What you get

- 🗺️ **A radial coverage map** — your brand at the center, categories → topics on the rings, every topic colour-coded by who leads.
- 🔍 **Click any topic** → the exact sentences each site wrote on it, with links to the source pages (the receipts).
- 🏷️ **Plain-English topic names** — auto-labelled by a local AI model (e.g. *"Health Insurance Benefits"*, not keyword soup).
- 📄 **Full transparency** — see every page analysed per domain, one click away.
- 🔒 **100% local & private** — your data never leaves the machine; no accounts, no API keys, no cost.

---

## ⚙️ How it works (one line)

**crawl each site → extract clean copy → embed it locally → cluster into shared topics → score who covers each topic more → draw the map.**

Topics are **discovered from the content itself** (never a hardcoded list), so the
map reflects *your* market, whatever it is.

---

## 🚀 Run it on your own computer

You need **Python 3.9+** and **git**. First install takes ~10 min (it downloads the
AI libraries); after that it starts in seconds. No API keys, no accounts.

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

Then open **http://localhost:8000** → enter your domain + competitors, set
**Max pages = 40** for a quick run, click **Analyze**. Or open
**http://localhost:8000/?run=1** first to see the seeded demo instantly.

### 🎁 Optional: even nicer topic names (free, local)
Labels default to keyword-based (readable). For plain-English names from a local
model, install [Ollama](https://ollama.com), run `ollama pull qwen2.5:3b`, then add
a `.env` file:
```
TC_LLM_LABELS=true
TC_LLM_PROVIDER=ollama
TC_LLM_MODEL=qwen2.5:3b
```

---

## 🧠 Under the hood

`FastAPI` · `sentence-transformers` (local embeddings) · `BERTopic` (topic
clustering) · `trafilatura` (polite crawling & extraction) · `SQLite` · vanilla
HTML/JS/SVG frontend. Every threshold lives in `config.py`. See **`SPEC.md`** for
the full build spec and **`CLAUDE.md`** for conventions.

---

## 🧩 Part of a small toolkit for understanding markets

- 🕸️ **Topic Coverage** *(this repo)* — who covers which topics, and who covers them more
- 🔤 **[Homepage Language Match](https://github.com/growthwithjoseph-bot/homepage-language-match)** — is your homepage messaging differentiated, or an echo of your competitors?
- 💬 **[Anatomy of a Brand Conversation](https://growthwithjoseph-bot.github.io/hubspot-brand-conversation/)** — how real people talk about a brand across the internet
