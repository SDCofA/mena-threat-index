<div align="center">
  <img src="docs/logo.png" alt="MENA Threat Index logo" width="140"/>
  <!-- CODEX: generate a clean, minimal product logo for "MENA Threat Index" — a stylized regional-risk gauge / compass dial over a faint MENA coastline silhouette, deep navy (#0b1f3a) on transparent, with a single accent arc; corporate, flat, no text or small "MTI" monogram. -->

  # MENA Threat Index
  ### Threat intelligence for the Middle East &amp; North Africa, refreshed every two hours

  ![status](https://img.shields.io/badge/status-active-brightgreen)
  ![division](https://img.shields.io/badge/Strategic%20Data%20Co.%20of%20Ankara-0b1f3a)
  ![Monarch Castle](https://img.shields.io/badge/Monarch%20Castle-Holdings-1f6feb)
  ![license](https://img.shields.io/badge/license-Apache--2.0-lightgrey)
  ![pipeline](https://img.shields.io/badge/refresh-every%202h-blue)
</div>

> **Executive summary** — The MENA Threat Index (MTI) converts the region's open news flow into a single, auditable 1–10 geopolitical-risk reading per country and a regional composite, refreshed every two hours. It forecasts that index forward and correlates it with global markets — oil, gold, FX, and defense equities — to estimate how prices respond to regional risk. MTI serves analysts, risk officers, and decision-makers who need a repeatable, evidence-backed situational-awareness signal rather than a one-off assessment. It is the successor to the **Border Neighbor Threat Index (BNTI)**, expanded from Türkiye's seven neighbours to all of MENA with a materially improved methodology.

## ✨ Highlights
- **24-country coverage, multilingual.** Ingests RSS and Google News across the MENA region, querying outlets in their dominant local language plus pan-regional English feeds.
- **Severity-weighted, auditable scoring.** Every headline maps to a fixed-weight event category; per-country scores apply recency decay, source-credibility weighting, and empirical-Bayes shrinkage — weights never change between runs, so any reading is reproducible.
- **Forward forecast with uncertainty bands.** An AR(1)/damped-Holt/persistence ladder projects the smoothed index 24 hours ahead with widening 80% predictive intervals.
- **Markets linkage.** Computes a lagged "threat beta" for instruments such as Brent, WTI, gold, the VIX, S&amp;P 500, defense/aerospace (ITA), and regional FX — with false-discovery control and BNTI-seeded launch statistics.
- **Confidence on every reading.** Each country and the composite ship with a 0–1 confidence score combining event volume, source diversity (Shannon entropy), and cross-source corroboration.
- **Fail-safe publishing.** Runs that fail validation or fall below feed-coverage thresholds are *withheld* — the last known-good snapshot stays live rather than publishing a degraded reading.
- **Zero-build static frontend.** A self-contained single-page app served from GitHub Pages, fully automated by a scheduled GitHub Actions pipeline.

## 🖼️ Preview
<!-- CODEX: drop product screenshots into docs/ -->
![MENA Threat Index — regional map and composite](docs/screenshot-1.png)
<!-- CODEX: capture the live app at https://sdcofa.github.io/mena-threat-index/ — the main map view showing the choropleth of MENA countries shaded by threat level, with the regional composite reading and status headline. -->

![MENA Threat Index — markets and forecast detail](docs/screenshot-2.png)
<!-- CODEX: capture the Markets screen and/or a country-detail panel showing the 24h forecast path with prediction bands and the lagged market-correlation ("threat beta") table. -->

## 🧭 What it does
MTI is a **news-frequency geopolitical-risk index**: it turns the volume and severity of regional reporting into a 1–10 level per country and a strategic-weighted regional composite, then forecasts that signal and ties it to market behaviour.

```
RSS / Google News (24 countries, multilingual)
        │  feeds.py        fetch · dedupe · 72h window
        ▼
   categorize.py           keyword engine (+ optional NVIDIA LLM)
        ▼
     score.py              recency-decay · source credibility · volume shrinkage
        │                  per-country index  = 1 + 9·(1 − e^(−raw/5·1.2))
        │                  composite          = strategic-weighted mean, EWMA spike-guard
        ▼
   history.py              append reading to data/history.jsonl  (persistent, growing)
        ▼
   forecast.py             AR(1)-with-drift (cold-start ladder) → 24h path + bands
        ▼
   markets.py              Yahoo + FRED prices · lagged correlation · "threat beta"
        │                  · BNTI-seeded · project market moves from forecast path
        ▼
   briefing.py             templated regional summary (+ optional LLM polish)
        ▼
   publish.py              assemble + validate → mena_data.json  (atomic, withhold-on-failure)
```

The frontend (`index.html` + `support.js`) is a static single-page app that fetches `mena_data.json` and renders the map, country detail, the trend-plus-forecast chart, the **Markets** screen, and the in-app methodology. `support.js` is a self-contained React-based template runtime — there is **no build step**.

### Methodology in brief
- **Categories → weights.** Each headline is assigned one category mapping to a fixed severity weight — military conflict 8, terrorism 7, border security 5, political instability 4, humanitarian crisis 3, diplomatic tensions 2.5, trade/de-escalation −2, neutral 0. The fixed-weight design follows event-data severity scales (Goldstein 1992; CAMEO) and keeps every run auditable.
- **Per-country score.** `1 + 9·(1 − e^(−eff/5·1.2))`, where `eff` is a recency-decayed (18 h half-life), source-credibility-weighted mean event weight, empirically-Bayes shrunk toward the country's trailing baseline. The level reflects **severity, not raw volume**.
- **Composite.** A strategic-weighted mean of country scores, smoothed with an asymmetric EWMA — responsive to genuine spikes, resistant to two-hour whipsaw.
- **Forecast.** An AR(1)/damped-Holt/persistence ladder on the smoothed series, 24 h ahead, with widening 80% predictive bands.
- **Markets.** A lagged "threat beta" per instrument via the market-model event-study approach, gated by minimum sample, sign stability, a lag-search correction, and Benjamini–Hochberg false-discovery control. Association, **not** causation; launch-day statistics are seeded from BNTI and badged as such.

Full formulas, constants, and the academic references behind them live in `config/settings.yml`, the in-app **Methodology** page, and [`METHODOLOGY_REVIEW.md`](METHODOLOGY_REVIEW.md).

## 🗂️ Data &amp; provenance
Per Monarch Castle doctrine — **evidence before assertion**. MTI collects only from open, lawfully accessible sources and keeps every reading traceable.

- **News sources.** Curated outlet RSS/Atom feeds plus a guaranteed Google News RSS layer, across 24 MENA countries and multiple languages. Pan-regional feeds (Al Jazeera, Middle East Eye, The New Arab, Al-Monitor) are fetched once and attributed to a country only when a headline names it.
- **Market sources.** Price series are pulled key-free from Yahoo Finance (with FRED fallbacks) for energy, metals, rates, equities, and FX instruments defined in `config/markets.yml`.
- **Provenance on every datum.** Each event carries its source, collection window, recency-decayed weight, and source-credibility factor; composite and per-country histories are stored append-only in `data/history.jsonl` and `data/countries/*.jsonl` as the system's source of truth. Per-run market snapshots are written to `data/markets/instruments.jsonl`.
- **Lawful collection.** Public sources only; the optional LLM step reads its key strictly from the environment and never persists it. Runs that fail schema validation or coverage thresholds are withheld, not published.

> **Situational-awareness aid — not an intelligence assessment.** The index reflects the volume and severity of *published reporting*, not ground truth. Coverage is uneven across languages, machine categorization introduces noise, and short-sample correlations are unstable and associative. Treat MTI as a monitoring aid.

## 🛠️ Tech stack
- **Pipeline:** Python 3.11 — `feedparser`, `requests`, `numpy`, `pandas`, `PyYAML`. All statistics (AR(1), OLS, Newey–West, correlation, bootstrap) are implemented in NumPy to keep the pipeline lean and CI-robust.
- **Optional LLM:** NVIDIA's OpenAI-compatible API (`integrate.api.nvidia.com`, default model `meta/llama-3.3-70b-instruct`) for headline categorization and briefing polish. Entirely optional — the pipeline runs deterministically on the keyword engine when no key is present.
- **Frontend:** Static single-page app — `index.html` + `support.js` (a self-contained React-based template runtime). No build step, no bundler.
- **Markets data:** Yahoo Finance + FRED (no API key required).
- **Automation:** GitHub Actions — a scheduled pipeline (`cron: every 2 hours`) recomputes the index, commits `mena_data.json` and `data/`, and deploys Pages.
- **Hosting:** GitHub Pages (static). **Live:** <https://sdcofa.github.io/mena-threat-index/>
- **Testing:** `pytest` suite covering feeds, categorization, scoring, forecasting, markets, schema, and the frontend data contract.

### Repository layout
| Path | What |
|---|---|
| `index.html` | The web app (served by GitHub Pages). |
| `support.js` | Template runtime. |
| `mena_data.json` | Latest published snapshot — committed by the pipeline. |
| `config/*.yml` | Countries + feeds, market instruments, category lexicon, settings. |
| `pipeline/*.py` | The data pipeline (run with `python -m pipeline.run`). |
| `data/history.jsonl` | Append-only composite history (source of truth). |
| `data/countries/*.jsonl` | Per-country history. |
| `data/markets/instruments.jsonl` | Per-run market snapshots. |
| `data/seed/` | Former BNTI history, used to seed correlations. |
| `scripts/` | One-off utilities — BNTI seeding, forecast backtest, sensitivity analysis. |
| `.github/workflows/` | Scheduled pipeline + Pages deploy. |
| `tests/` | `pytest` suite. |

## 🚀 Getting started
**Live deployment:** <https://sdcofa.github.io/mena-threat-index/>

### Run the pipeline locally
```bash
pip install -r requirements.txt

# Deterministic run (keyword categorizer, no LLM):
python -m pipeline.run

# With LLM categorization + briefing polish (NVIDIA, OpenAI-compatible API):
export NVIDIA_API_KEY=nvapi-xxxxxxxx        # Windows PowerShell: $env:NVIDIA_API_KEY="nvapi-..."
python -m pipeline.run

# Serve the site:
python -m http.server 8000      # then open http://localhost:8000/
```

`python -m pipeline.run` writes/refreshes `mena_data.json`, appends to `data/`, and **withholds** the update (keeps the last-good file) if the run fails validation or feed coverage is too low. Run the test suite with `pytest`.

### Deploy (GitHub Pages + Actions)
1. Push this repository and set **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. *(Optional)* Add `NVIDIA_API_KEY` under **Settings → Secrets and variables → Actions**. The pipeline runs fully without it, using the keyword categorizer.
3. The **MTI Pipeline** workflow runs every 2 hours (cron), recomputes the index, commits `mena_data.json` + `data/`, and deploys Pages. Trigger it manually via **Actions → MTI Pipeline → Run workflow.**

> 🔐 **Security.** The NVIDIA key lives only as a GitHub Actions secret, read from `NVIDIA_API_KEY` at runtime, and is never written to any file in this repo. If a key was ever exposed in plaintext, rotate it at <https://build.nvidia.com>.

## 🧱 Part of Monarch Castle
> A product of the **Strategic Data Company of Ankara** — an operating company of **[Monarch Castle Holdings](https://github.com/MonarchCastleHoldings)**.
> Sister companies: [Monarch Castle Technologies](https://github.com/monarchcastletech) · [Strategic Data Company of Ankara](https://github.com/SDCofA)

## 📜 License
Licensed under **Apache-2.0** — see [`LICENSE`](LICENSE). © 2026 Monarch Castle Holdings · Ankara, Türkiye.

<div align="center"><sub>🏰 Monarch Castle Holdings — turning open-source noise into lawful, verified, decision-grade intelligence.</sub></div>
