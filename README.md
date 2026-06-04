# X-Digest

> **5 minutes · 200+ tech KOLs · $0 API cost**
> A daily, decision-grade tech briefing — not another tweet RSS.

[简体中文](README.zh-CN.md) · [Quick Start](#quick-start) · [Configuration Guide](docs/configuration-guide.md)

---

## A Real Scenario

You follow 233 tech accounts. Last night they posted 800 tweets.

- 9:00 AM, 30 minutes until your weekly meeting.
- You open the X client. The feed mixes *Sam Altman on GPT-6 rumors*, *some KOL's breakfast photo*, and *Sora 2 video leaks*.
- After 30 minutes, you've seen 50 tweets, 5 are useful.
- You missed the *NVIDIA Blackwell B200 benchmark*, and a $50K B2B lead that came from it.

**X-Digest finishes this work while you sleep:**

- ✅ Compresses 800 tweets into 30, each scored by **two independent AI judges**
- ✅ Auto-translates non-Chinese tweets, **preserving the original for reference**
- ✅ Auto-writes "💡 Tip" and "🧠 Insight" — you read the takeaway, not the raw text
- ✅ Pushes to Feishu — read on the way to the meeting, 3 minutes tops

---

## See It In Action

This is a real output from `test_pipeline.py` ([B200 GPU tweet](https://x.com/NVIDIAGeForce)):

> **@NVIDIAGeForce**
>
> 🔗 [Original tweet](https://x.com/NVIDIAGeForce)
> *Our Blackwell B200 GPU features 208 billion transistors and is connected by the 1.8TB/s Fifth-Generation NVLink. This is a massive leap for LLM training.*
>
> 📝 **Translation**: Our Blackwell B200 GPU packs 208 billion transistors and connects them via 1.8TB/s 5th-gen NVLink. This is a major leap for LLM training.
>
> 💡 **Tip**: B200 is NVIDIA's latest GPU — 208 billion transistors squeezed into a chip the size of a fingernail, the equivalent of cramming an entire city's population into one room. NVLink is the chip-to-chip superhighway; 5th-gen runs 10× faster than fiber, purpose-built for training large AI models.
>
> 🧠 **Insight**: With the AI compute arms race heating up, B200's transistor density and interconnect bandwidth directly determine large-model training efficiency. This hardware breakthrough will accelerate the proliferation of trillion-parameter models and likely trigger a new wave of AI applications.

**Every tweet becomes a decision artifact** — not "read English again" but "get the background, the significance, and the action".

---

## 3-Step Pipeline

```
┌──────────────┐     ┌────────────────────┐     ┌────────────────┐
│  ① Fetch     │     │  ② Analyze         │     │  ③ Deliver     │
│  Playwright  │ ──> │  Cross-endpoint    │ ──> │  Feishu / Doc  │
│  multi-accnt │     │  dual-score + LLM  │     │  PDF / file    │
└──────────────┘     └────────────────────┘     └────────────────┘
   72h rolling          dual-AI 80pt cut         Markdown / Feishu
```

| Stage | Duration | Capability |
|-------|----------|------------|
| Fetch | 3 min (3 accounts) | 72h rolling pool, Per-Context isolation, auto cooldown |
| Analyze | 5-8 min | Cross-endpoint dual-score, auto-analogy, insight generation |
| Deliver | 10s | Feishu group / Feishu doc / PDF / local archive |

> End-to-end single pipeline: **< 12 minutes**. Run on schedule, wake up to a fresh briefing.

---

## Why Not the X Official API?

| Plan | Monthly | Read quota | Reality |
|------|---------|------------|---------|
| X Free | $0 | **Cannot read** | No tweet access |
| X Basic | **$200/mo** | 10,000 / month | 200 accounts × 50 tweets = done |
| X Pro | **$5,000/mo** | 1M / month | Out of reach for individuals |
| **X-Digest** | **$0** | **Unlimited** | Cookie-mount + browser automation |

Save **$2,400+ / year** (≈ ¥17,000), with more data, a wider search window, and AI built in.

---

## Core Features

### 1. Cross-Endpoint Dual-Score Engine

Two independent AI judges on **different endpoints** score in parallel; the intersection passes — fewer misses, no single-model bias:

```
sensenova-6.7-flash-lite   @token.sensenova.cn/v1   ─┐
                                                    ├─> ≥80pt intersection
DeepSeek-R1-Distill-Qwen-14B @api.sensenova.cn/v2  ─┘
```

**Why:** A single AI scorer overfits its own preferences (likes short ones, likes technical ones, ignores Chinese). Two engines + different endpoints = mutual error-correction + rate-limit isolation. See `pipeline/score.py:42`.

### 2. AI Translation That's Free Forever

**DeepSeek-R1-Distill-Qwen-14B** for translation, 67% terminology retention (vs. V3-1/R1 at 48%). **Free forever** — not affected by the 2026-08-09 promo expiry.

### 3. Multi-Account Concurrent Fetching

Drop `x_cookies_1.json` to enable 1 lane, drop 3 to enable 3 lanes — **linear scaling**. 8 minutes for 200 accounts with 1 cookie, 3 minutes with 3 cookies.

### 4. 72h Rolling Tweet Pool

Even if you only scan a subset of accounts each day, all tweets from the past 72 hours are auto-merged and deduped — **no gaps, no duplicates**.

### 5. Auto-Analogy & Insight

Every tweet ships with "💡 Tip" (term explainer) and "🧠 Insight" (industry significance). Readable for non-experts, immediately useful for experts.

### 6. Feishu-Native Delivery

Reports are pushed directly to Feishu groups, Feishu docs, and PDF attachments. Open Feishu, skim in 3 minutes, walk into the meeting.

---

## Quick Start

### Up and running in 5 minutes

```bash
# 1. Install dependencies (Python 3.12+)
uv pip install -r requirements.txt
uv run playwright install chromium

# 2. Configure API keys
cp .env.example .env
# Edit .env, fill in SENSENOVA_API_KEY (SenseNova by default — zero cost)

# 3. Export Twitter cookies
# Install Cookie-Editor in Chrome → log in to X → export JSON
# Save as x_cookies_1.json (multi-account: x_cookies_2.json, ...)

# 4. Run
uv run python main.py
```

Interactive UI guides you through domain selection, look-back window, and report generation. One click, one daily briefing.

Non-interactive mode (used by CI):
```bash
uv run python main.py --manual --hours 24
```

### Project Structure

```
x-digest/
├── main.py                  # Entry + interactive UI + Feishu push
├── fetcher.py               # Multi-account concurrent fetch engine
├── config.py                # Provider fallback chain + runtime config
├── pipeline/                # AI processing pipeline
│   ├── score.py             #   Cross-endpoint dual-score engine
│   ├── translate.py         #   Translation (Distill-14B)
│   ├── insights.py          #   Insights (sensenova-6.7-flash-lite)
│   ├── curate.py            #   Curation & dedup
│   ├── assemble.py          #   Report assembly
│   └── orchestrator.py      #   Pipeline orchestration
├── custom_accounts.json     # Followed accounts (6 domains, 233 accounts)
├── defaults/                # Recommended accounts
├── docs/                    # Configuration guide
└── output/                  # Briefings + PDFs + audit reports
```

---

## Roadmap

- [x] Cross-endpoint dual-score engine (v2.0, 2026-06)
- [x] Free-forever AI translation (v2.0)
- [x] Feishu-native delivery (v1.5)
- [ ] WeChat / email subscriptions (v3.0)
- [ ] Custom categories and multi-tenancy (v3.0)
- [ ] Desktop / iOS widget push (v3.5)

---

## Advanced Configuration

See [`docs/configuration-guide.md`](docs/configuration-guide.md). Highlights:

| Concern | Where to configure |
|---------|---------------------|
| AI provider fallback chain | `.env`: `AI_PROVIDER_CHAIN=SENSENOVA,GROQ,OPENROUTER` |
| Scoring models (dual engine) | Hardcoded in `pipeline/score.py` |
| Translation model | `AI_MODEL_TRANSLATE=DeepSeek-R1-Distill-Qwen-14B` |
| Insight model | `AI_MODEL_INSIGHTS=sensenova-6.7-flash-lite` |
| Followed accounts | `custom_accounts.json` |
| Feishu credentials | GitHub Secrets |

---

## Credits

- Fetching: [Playwright](https://playwright.dev/python/) + [playwright-stealth](https://github.com/nicedouble/playwright-stealth-python)
- AI: [SenseNova](https://platform.sensenova.cn/) + [Token Plan](https://token.sensenova.cn/) (free during promo period)
- Delivery: [Feishu Open Platform](https://open.feishu.cn/)

---

## License

[MIT](LICENSE) · For learning and research only. Please respect X's Terms of Service.

---

<p align="center">
  <i>Built with Playwright, powered by AI. Engineered for insight.</i>
</p>
