# Polymarket Bot Analysis Plan

## Target
**Account:** Uncommon-Oat (`0xd0d6053c3c37e727402d84c14069780d360993aa`)
https://polymarket.com/@k9Q2mX4L8A7ZP3R
- 13,508+ trades (still actively trading every minute) | $86.8M volume | $698K profit | ~7 weeks active
- Initial hypothesis: 0.8% profit/volume ratio suggests market making or arbitrage

---

## Phase 1: Project Setup & Foundation

**Goal:** Set up the project skeleton, dependencies, config, and core infrastructure.

**Files to create:**
- `requirements.txt` — `httpx`, `pandas`, `numpy`, `matplotlib`, `plotly`, `tenacity`, `tqdm`
- `config.py` — Wallet address, API base URLs (Data API, Gamma API), rate limits, pagination limits, DB/cache paths
- `storage/__init__.py`
- `storage/models.py` — Dataclasses matching exact API camelCase field names: `Trade`, `Market`, `Position`, `ClosedPosition`
- `storage/database.py` — SQLite schema (`trades`, `markets`, `positions`, `closed_positions`, `collection_metadata` tables), connection management, upsert methods, DataFrame loaders with enriched JOIN query
- `collectors/__init__.py`
- `collectors/api_client.py` — `RateLimitedClient` class: file-based response caching (hash of URL+params as key), token-bucket rate limiting, retries via `tenacity`

**Key design decisions (validated by API testing):**
- `httpx` over `requests` — async-ready, connection pooling, HTTP/2 support
- `tenacity` for retries — no hand-rolled exponential backoff
- No `scipy` — pandas+numpy sufficient for our analysis
- `sqlite3` (built-in) — fine for 13K+ records, no extra dependency
- All API responses are **bare JSON arrays** (not wrapped in `{data: [...]}`)
- API fields are **camelCase** — store as-is, convert in DataFrame loaders
- Gamma API returns **strings for numeric fields** (volume, liquidity) — type conversion in storage layer
- **No pagination metadata** in API responses — detect end-of-data by `len(results) < limit`
- `collection_metadata` table stores `last_trade_timestamp` for **incremental fetching** (bot is still actively trading, so re-runs should only fetch new trades)

**Verify:** `pip install -r requirements.txt`, import all modules without errors, database initializes and creates tables.

---

## Phase 2: Data Collection

**Goal:** Fetch all trades, market metadata, and positions into SQLite.

**Files to create:**
- `collectors/trade_collector.py` — Fetch all trades via `GET /activity?user={wallet}&type=TRADE` using timestamp-windowed pagination (offset maxes at 10K, so after 10K results we set `start={last_timestamp}` and reset offset to 0). Supports incremental mode: on re-runs, only fetch trades newer than `last_trade_timestamp` from `collection_metadata`. Also fetch `type=MAKER_REBATE` activity (only `usdcSize` + `timestamp` are populated). Deduplicate by `(transactionHash, asset)`.
- `collectors/market_collector.py` — Batch-fetch market metadata via `GET /markets?condition_ids={batch}` from Gamma API for all unique conditionIds. Handle string→number conversion for `volume`, `liquidity`, `outcomePrices`.
- `collectors/position_collector.py` — Fetch current positions (`/positions`) and closed positions (`/closed-positions`). Note: closed positions have a different/smaller field set than open positions.
- `main.py` (partial — collection phase only)

**Verified API response schemas:**
- `/activity` returns: `proxyWallet`, `timestamp`, `conditionId`, `type`, `size`, `usdcSize`, `transactionHash`, `price`, `asset`, `side`, `outcomeIndex`, `title`, `slug`, `icon`, `eventSlug`, `outcome`, `name`, `pseudonym`, `bio`, `profileImage`, `profileImageOptimized`
- `/positions` returns: `proxyWallet`, `asset`, `conditionId`, `size`, `avgPrice`, `initialValue`, `currentValue`, `cashPnl`, `percentPnl`, `totalBought`, `realizedPnl`, `percentRealizedPnl`, `curPrice`, `redeemable`, `mergeable`, `title`, `slug`, `icon`, `eventId`, `eventSlug`, `outcome`, `outcomeIndex`, `oppositeOutcome`, `oppositeAsset`, `endDate`, `negativeRisk`
- `/closed-positions` returns: `proxyWallet`, `asset`, `conditionId`, `avgPrice`, `totalBought`, `realizedPnl`, `curPrice`, `title`, `slug`, `icon`, `eventSlug`, `outcome`, `outcomeIndex`, `oppositeOutcome`, `oppositeAsset`, `endDate`, `timestamp`
- Gamma `/markets` returns: `id`, `question`, `conditionId`, `slug`, `endDate`, `category`, `liquidity`, `description`, `outcomes`, `outcomePrices`, `volume`, `active`, `marketType`, `closed`, `marketMakerAddress`, `createdAt`, `updatedAt`, `volumeNum`, `liquidityNum`, `clobTokenIds`, `events`, `negRisk`, and more

**Verify:** Run collection, confirm ~13,500+ trades in DB, ~200-400 markets, date range matches (Dec 2025 to present). Query total USDC volume and compare to $86.8M.

---

## Phase 3: Core Analyzers (Temporal + Market Selection + Entry/Exit)

**Goal:** Build the first three analyzers that reveal fundamental trading behavior.

**Files to create:**
- `analyzers/__init__.py`
- `analyzers/temporal.py` — Trade frequency (per day/hour), inter-trade intervals, time-of-day heatmap, 24/7 detection, speed of entry after market creation, hold durations via position-crossing-zero tracking
- `analyzers/market_selection.py` — Category distribution, market volume/liquidity/spread preferences, concentration (Herfindahl index), lifecycle preference (new vs established vs near-expiry markets)
- `analyzers/entry_exit.py` — Entry price distribution (near 0.50 = market making, near extremes = directional), YES vs NO preference, spread capture per market, both-sides detection (trades both YES and NO in same market)

**Verify:** Run each analyzer on the collected data, print summary stats. Check: avg trades/day, unique market count, median entry price, both-sides market percentage.

---

## Phase 4: Advanced Analyzers (Position Sizing + Maker/Taker + P&L)

**Goal:** Build the deeper analytical modules that reveal strategy mechanics.

**Files to create:**
- `analyzers/position_sizing.py` — Trade size distribution, scaling behavior (constant/in/out), max position per market, concurrent positions over time
- `analyzers/maker_taker.py` — Uses MAKER_REBATE count (definitive proof of maker activity — only `usdcSize` and `timestamp` fields are populated in rebate records), both-sides detection, price precision heuristics, trade size clustering → classifies as PRIMARILY_MAKER, PRIMARILY_TAKER, or MIXED
- `analyzers/pnl.py` — Per-market realized P&L (FIFO cost basis), cross-validate against `/closed-positions` endpoint `realizedPnl` field, cumulative P&L curve, win/loss stats (win rate, avg win/loss, expectancy, profit factor), risk metrics (Sharpe, Sortino, max drawdown, Calmar), P&L by category

**Verify:** Compare computed total P&L to the profile's $698K. Check maker/taker classification is decisive. Confirm risk metrics are reasonable.

---

## Phase 5: Strategy Classification

**Goal:** Synthesize all analyzer outputs to classify the bot's strategy.

**Files to create:**
- `analyzers/strategy_classifier.py` — Scores the bot (0-100) against 4 archetypes using weighted signals:
  - **Market Making:** high maker%, both-sides trading, mid-range entry prices, tight spreads, high frequency, 24/7
  - **Directional:** high taker%, strong YES/NO bias, extreme entry prices, category concentration
  - **Arbitrage:** YES+NO buys summing <$1.00, very fast paired execution, consistent small profits
  - **Event-Driven:** trades cluster after market creation, rapid entry, large directional sizes
- Outputs: primary strategy, confidence (STRONG/MODERATE/WEAK), evidence list

**Verify:** Classification produces a clear winner with supporting evidence. Manual review of top evidence items against raw data.

---

## Phase 6: Report Generation & Final Pipeline

**Goal:** Generate visual report and wire up the complete pipeline.

**Files to create:**
- `reporting/__init__.py`
- `reporting/charts.py` — ~15 chart functions: daily trade bar chart, hourly heatmap, inter-trade interval histogram, entry price distribution, YES/NO volume comparison, trade size distribution, concurrent positions line chart, cumulative P&L curve, drawdown chart, P&L by category, win/loss histogram, strategy radar chart
- `reporting/report_generator.py` — Assembles HTML report with embedded charts, 8 sections (Executive Summary, Temporal, Market Selection, Trading Behavior, Position Management, Maker/Taker, Performance, Strategy Classification)
- `main.py` (complete) — CLI with `--skip-fetch` and `--wallet` flags, runs full pipeline: collection → analysis → classification → report

**Verify:** Run `python main.py`, open `output/report.html` in browser. All charts render, findings are coherent, strategy classification matches manual observations.

---

## API Reference (no auth required)

| Endpoint | Base URL | Use |
|----------|----------|-----|
| `GET /activity?user={wallet}&type=TRADE` | `data-api.polymarket.com` | All trades |
| `GET /activity?user={wallet}&type=MAKER_REBATE` | `data-api.polymarket.com` | Maker detection |
| `GET /positions?user={wallet}` | `data-api.polymarket.com` | Open positions |
| `GET /closed-positions?user={wallet}` | `data-api.polymarket.com` | Closed positions + P&L |
| `GET /markets?condition_ids={batch}` | `gamma-api.polymarket.com` | Market metadata |

**Pagination:** No pagination metadata in responses. Detect end-of-data by `len(results) < limit`. Offset maxes at 10,000 — use timestamp windowing beyond that.

**Response format:** All endpoints return bare JSON arrays. Field names are camelCase. Gamma API returns some numeric fields as strings.

## Dependencies
```
httpx>=0.27.0
pandas>=2.1.0
numpy>=1.24.0
matplotlib>=3.8.0
plotly>=5.18.0
tenacity>=8.2.0
tqdm>=4.66.0
```
