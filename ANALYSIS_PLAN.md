# Polymarket Bot Analysis Plan

## Target
**Account:** Uncommon-Oat (`0xd0d6053c3c37e727402d84c14069780d360993aa`)
https://polymarket.com/@k9Q2mX4L8A7ZP3R
- 1,323,832 fills across 8,313 markets (15-min crypto Up/Down) | $20.5M USDC volume | $713K realized P&L | 22 days active (Jan 19 – Feb 10, 2026)
- Profile shows "13,508 predictions" (market-level count) and "$86.8M volume" (double-counted or notional per Paradigm research)
- 26,310 closed positions: 13,158 winners (cur_price=1) vs 13,152 losers (cur_price=0) — nearly perfect 50/50 resolution split
- $40,704 in maker rebates across 34 daily payouts — significant revenue source
- **Strategy hypothesis:** Completeness arbitrage on crypto 15-minute markets — buying both Up and Down outcomes at combined VWAP < $1.00, with directional tilt toward predicted winner

---

## What the Data Reveals (pre-analysis profiling)

| Metric | Value | Implication |
|--------|-------|-------------|
| Total fills | 1,323,832 | Individual order fills, 99.85% are 1-fill-per-tx (not partial fills of large orders) |
| Unique markets | 8,313 | ~370/day ≈ 4 concurrent crypto assets across 96 daily 15-min windows |
| Outcomes | Only "Up" and "Down" | Exclusively crypto price-direction markets (BTC/ETH/SOL 15-min) |
| BUY/SELL split | 88.6% BUY / 11.4% SELL | Accumulator — buys to hold, rarely exits early |
| Up vs Down BUYs | 50.2% Up / 49.8% Down | No directional bias overall — buys both sides |
| Both-sided markets | 95.6% (7,947 of 8,313) | Buys BOTH Up and Down in nearly every market |
| Up-only / Down-only | 164 / 202 | Only 4.4% are purely directional bets |
| Avg combined VWAP | $0.9287 (Up+Down) | 7.13% average spread captured per market before costs |
| Avg trade size | $15.50 USDC | Small orders sweeping available liquidity |
| Trades/minute | 46.7 avg, 748 peak | High-frequency automated execution |
| Max trades/second | 109 | Burst-mode liquidity sweeping |
| Market duration | 88.2% under 15 min | Confirms 15-minute market windows |
| Market start times | Cluster at :00, :15, :30, :45 | Aligned to standard 15-min crypto market intervals |
| Hour-of-day peak | 10:00–19:00 UTC | US market hours bias — not 24/7 |
| Maker rebates | 34 payouts, $40,704 total | Significant maker activity — $1,197/day avg rebate changes the taker-only assumption |
| Closed positions | 26,310 (13,158 W / 13,152 L) | 50/50 win/loss on outcomes; P&L comes from spread, not direction |
| Realized P&L | $713,043 (positions) | Ground truth from closed-positions API, includes all settled markets |
| Sell pattern | Sells exist in 36.5% of markets | Position management — rebalancing or early exit, never sell-only |

---

## Phase 1: Project Setup & Foundation — COMPLETE

Infrastructure is built and working. See `config.py`, `storage/`, `collectors/`, `main.py`.

**Key design notes for remaining phases:**
- SQLite with WAL mode handles 1.3M records well for storage, but **all analysis must use SQL-level aggregation** — never `load_trades()` into a single DataFrame
- Add helper methods to `database.py` that return pre-aggregated results (per-market rollups, daily summaries, etc.)
- The `seen` set pattern in `trade_collector.py` consumed significant memory at 1.3M scale — not a problem now that trades are collected, but note for any future incremental runs

---

## Phase 2: Data Collection — COMPLETE

### Collected datasets:
- **1,323,832 trades** — complete history, Jan 19 – Feb 10 2026, no gaps
- **8,313 markets** — metadata from Gamma API via `clob_token_ids` batches (75/batch, 111 API calls, ~55 sec)
- **26,331 positions** — 21 open + 26,310 closed (paginated at 50/page, 527 API calls, ~2.5 min)
- **34 maker rebates** — $40,704 total (single page)
- **WAL checkpointed** — DB stabilized at 762 MB

### Key API learnings (documented for future use):
- **Gamma API:** `condition_ids` param does NOT work for batch lookups. Must use `clob_token_ids` with array format (`?clob_token_ids=X&clob_token_ids=Y`). Default limit=20, can increase with `limit` param. URL length caps at ~75 tokens per batch.
- **Closed positions:** Page size capped at 50 regardless of requested limit. Supports `offset` param with no upper limit. 26,310 total records for this wallet.
- **Position schema expanded:** Added `total_bought`, `cur_price` (resolution: 0 or 1), `opposite_outcome`, `opposite_asset`, `end_date`, `close_timestamp`, `initial_value`, `cash_pnl` — critical for P&L analysis.
- **Market schema expanded:** Added `neg_risk`, `neg_risk_market_id`.

### Verification results:
- Market coverage: 8,313/8,314 condition_ids found (1 missing from Gamma — negligible)
- Market questions confirm format: "Solana Up or Down - January 19, 7:45AM-8:00AM ET"
- Realized P&L from positions: **$713,043** (ground truth)
- Resolution split: 13,158 winners (cur_price=1) vs 13,152 losers (cur_price=0) — 50.01%
- Position condition_ids: 13,543 (more than 8,314 in trades — bot has older positions pre-dating our trade window)

---

## Phase 3: Market Structure & Completeness Arbitrage Analysis

**Goal:** Understand the market universe this bot operates in and quantify the core completeness arbitrage strategy.

**Files to create:**
- `analyzers/__init__.py`
- `analyzers/market_structure.py` — Identify and categorize the crypto markets:
  - Parse market `question` text to extract: crypto asset (BTC/ETH/SOL/etc.), time window, direction type
  - Distribution of markets by crypto asset (how many BTC vs ETH vs SOL)
  - Confirm 15-min duration via `endDate - created_at` or `endDate` parsing
  - Market liquidity/volume context from Gamma metadata
  - Identify the ~4.4% one-sided (directional-only) markets — are they a different crypto asset or different market conditions?
  - NegRisk flag analysis: are these negRisk markets? (multi-outcome crypto markets often are)

- `analyzers/completeness.py` — Core arbitrage mechanics:
  - **Per-market completeness calculation:** For each condition_id with both Up and Down buys:
    - Volume-weighted average price (VWAP) for Up buys and Down buys
    - Combined VWAP = VWAP_up + VWAP_down (cost of a matched pair)
    - Matched shares = MIN(total_up_shares, total_down_shares) — guaranteed-profit portion
    - Unmatched shares = excess on one side — directional exposure
    - Guaranteed spread = matched_shares × (1.00 - combined_VWAP)
    - Directional exposure = unmatched_shares × VWAP_of_excess_side
  - **Spread distribution:** Histogram of (1.00 - combined_VWAP) across all markets — how consistent is the edge?
  - **Sell impact:** For markets with sells, recalculate net position after sells — did selling improve or reduce the spread?
  - **Evolution over time:** Is the average spread improving, degrading, or stable across the 22-day window? (competition signal)
  - **All SQL-based:** Use a CTE that computes per-condition_id aggregates, return summary DataFrame

**Verify:** Average combined VWAP should be ~$0.9287 (pre-computed). Spread distribution should show a tight cluster around 7%. Cross-check: total_matched_shares × avg_spread ≈ rough profit estimate, compare to $713K.

---

## Phase 4: Execution Microstructure Analysis

**Goal:** Reverse-engineer HOW the bot executes — fill patterns, timing, order flow, and position building within each 15-minute window.

**Files to create:**
- `analyzers/execution.py` — Intra-market execution patterns:
  - **Fill timeline per market:** For each condition_id, sequence of (timestamp, side, outcome, price, size). Analyze:
    - Does the bot buy Up first, then Down? Or interleave? Or simultaneous?
    - Time from market open (:00/:15/:30/:45) to first fill (entry speed)
    - Time from first fill to last fill (execution duration)
    - Fill rate over the window (front-loaded, steady, or back-loaded?)
  - **Price trajectory within market:** Does the bot's average price worsen over the window as it consumes liquidity? (slippage measurement)
  - **Up vs Down sequencing:** In both-sided markets, compute time gap between first Up fill and first Down fill — simultaneous entry or sequential?
  - **Burst detection:** Identify concentrated fill clusters (>10 fills within 5 seconds) — these are likely single order sweeps across the book
  - Sample analysis on top-50 markets by trade count, then validate patterns hold across full dataset via SQL aggregates

- `analyzers/sizing.py` — Position sizing and capital deployment:
  - **Per-market capital deployed:** Total USDC spent per condition_id (buy - sell)
  - **Capital deployment distribution:** Histogram of per-market spend — is it uniform or heavy-tailed?
  - **Balance ratio per market:** up_cost / (up_cost + down_cost) — how tilted is the directional bet?
    - 0.50 = perfectly balanced completeness arb
    - 0.70+ or 0.30- = strong directional conviction
  - **Concurrent capital:** At any point in time, how much capital is locked in unresolved markets?
  - **Daily capital deployment:** Total USDC deployed per day — is the bot scaling up, stable, or scaling down?
  - **Fill size patterns:** Distribution of individual fill sizes — constant, random, or strategic (e.g., larger early, smaller as liquidity thins)?

**Verify:** Entry speed distribution should show most markets entered within first 1-2 minutes. Balance ratio distribution should cluster near 0.50 (completeness) with a tail toward directional tilts.

---

## Phase 5: P&L and Performance Analysis

**Goal:** Decompose where the bot's $713K profit comes from and measure the quality of its edge.

**Files to create:**
- `analyzers/pnl.py` — Profit & loss decomposition:
  - **Per-market P&L (SQL-based):** For each condition_id:
    - Total buy cost (Up + Down), total sell proceeds
    - Net shares held at resolution: up_shares_net, down_shares_net (buys - sells per outcome)
    - Resolution P&L: winning_shares × $1.00 + losing_shares × $0.00 - total_cost + sell_proceeds
    - **Resolution price now available:** `cur_price` field in positions table (1=won, 0=lost)
    - **Ground truth available:** `realized_pnl` per position from closed-positions API ($713K total)
    - **Cross-validate:** Computed P&L from trades should match `realized_pnl` from positions
  - **P&L decomposition into three components:**
    1. **Completeness spread:** matched_shares × (1.00 - combined_VWAP) — the guaranteed arb profit
    2. **Directional P&L:** unmatched_shares × (resolution_price - entry_price) — the speculative component (win or lose)
    3. **Early exit P&L:** sell_proceeds - cost_basis_of_sold_shares — profit/loss from selling before resolution
  - **Win/loss statistics:**
    - Market-level win rate (% of markets with positive P&L)
    - Average win vs average loss
    - Profit factor (gross_wins / gross_losses)
    - Expectancy per market
  - **By-asset breakdown:** P&L by crypto asset (BTC vs ETH vs SOL) — which is most profitable?
  - **Cumulative P&L curve:** Daily P&L aggregated into running total (use closed-position timestamps for timing)

- `analyzers/risk.py` — Risk metrics:
  - **Sharpe ratio** (daily P&L series)
  - **Max drawdown** (peak-to-trough on cumulative P&L)
  - **Calmar ratio** (annualized return / max drawdown)
  - **Loss streaks:** Maximum consecutive losing markets
  - **Tail risk:** Worst 5% of market-level outcomes
  - **Capital efficiency:** Profit / average capital deployed

**Verify:** Sum of per-market P&L should match $713K (from positions ground truth). Completeness spread component should account for the majority of profit. Directional component should be positive but smaller (edge in direction prediction). Win rate should be high (>80%) if completeness arb dominates. Maker rebates ($40.7K) are an additional revenue source to include.

---

## Phase 6: Temporal & Behavioral Patterns

**Goal:** Identify when and why the bot trades, and detect any behavioral signals that reveal its decision-making logic.

**Files to create:**
- `analyzers/temporal.py` — Time-based patterns:
  - **Daily activity profile:** Trades per hour-of-day (UTC) — confirm US hours bias, identify exact active window
  - **Day-of-week pattern:** Does activity vary by weekday? (crypto markets are 24/7 but bot may have human oversight patterns)
  - **Ramp-up / ramp-down:** Activity level over the 22-day period — is the bot increasing activity (deployment), stable (production), or decreasing (winding down)?
  - **Session detection:** Identify distinct trading sessions using gaps >30 minutes with no trades
  - **Market skip analysis:** During active hours, which 15-min windows does the bot skip entirely? What's different about skipped vs traded windows? (requires market metadata to check if markets existed but weren't traded)

- `analyzers/directional.py` — Directional conviction signals:
  - **One-sided market analysis:** The 366 markets (4.4%) where the bot bought only Up or only Down — what's different?
    - Were these markets with different characteristics (lower liquidity? different crypto asset?)
    - Was the directional choice correct (profitable)?
    - Size comparison: larger or smaller positions than both-sided markets?
  - **Tilt analysis:** In both-sided markets, compute the directional tilt (excess_shares / total_shares):
    - Tilt distribution — how often is the bot perfectly balanced vs heavily tilted?
    - Tilt accuracy — does tilting toward Up correlate with Up winning (and vice versa)?
    - Tilt magnitude vs profit — does stronger conviction lead to better outcomes?
  - **Sell trigger identification:** In the 36.5% of markets with sells:
    - Time of sell relative to market window (early, mid, late?)
    - Price at sell vs price at buy — selling at profit or loss?
    - Which side is sold (the same side as the tilt, or the opposite?)
    - Hypothesis: bot sells the losing side early to recover capital when direction becomes clear

**Verify:** One-sided markets should show clear directional conviction with measurable accuracy. Tilt accuracy > 50% would prove the bot has a directional model beyond pure arb. Sell triggers should reveal systematic rules.

---

## Phase 7: Strategy Synthesis & Report

**Goal:** Bring all analyzer outputs together into a coherent reverse-engineering conclusion and generate a visual report.

**Files to create:**
- `analyzers/strategy_synthesis.py` — Synthesize findings:
  - **Strategy decomposition:** Quantify the relative contribution of each profit source:
    1. Completeness arbitrage spread (guaranteed component)
    2. Directional prediction alpha (speculative component)
    3. Execution efficiency (slippage management, fill optimization)
    4. Early exit skill (sell timing)
  - **Edge identification:** What gives this bot its edge?
    - Speed: how fast does it enter after market opens vs typical market activity?
    - Pricing: does it consistently get better prices than the market average?
    - Coverage: trading ~370 markets/day across ~4 assets — does breadth explain the profit?
    - Model: does the directional tilt accuracy imply a price prediction model?
  - **Bot signature fingerprint:** Summarize the distinguishing characteristics:
    - Execution pattern (fill sizes, timing, sequencing)
    - Capital management (per-market sizing, concurrent exposure)
    - Active hours and session structure
    - Crypto asset preferences
  - **Replication feasibility:** What would it take to replicate this strategy?
    - Capital requirements (concurrent exposure estimate)
    - Infrastructure requirements (latency, API access)
    - Edge sustainability (is the 7% spread compressing over the 22-day window?)

- `reporting/charts.py` — Chart functions (all Plotly for interactive HTML):
  1. **Completeness spread distribution** — histogram of (1.00 - combined_VWAP) per market
  2. **Balance ratio distribution** — histogram showing tilt toward Up vs Down
  3. **Fill timeline (example market)** — scatter plot showing individual fills within a 15-min window
  4. **Daily P&L bar chart** — with cumulative overlay line
  5. **Cumulative P&L curve** — with drawdown shading
  6. **Hour-of-day heatmap** — trade count by day × hour
  7. **Per-asset P&L breakdown** — stacked bar (BTC/ETH/SOL)
  8. **Entry speed histogram** — time from market open to first fill
  9. **Spread evolution over time** — daily average combined VWAP trend (competition signal)
  10. **Directional tilt accuracy** — scatter of tilt magnitude vs market P&L
  11. **Capital deployment over time** — daily concurrent exposure
  12. **Trade size distribution** — log-scale histogram of fill sizes
  13. **P&L decomposition waterfall** — arb spread + directional + sells = total
  14. **Win rate by crypto asset** — grouped bar
  15. **Execution slippage** — price trajectory within market windows

- `reporting/report_generator.py` — HTML report assembly:
  - **Section 1: Executive Summary** — strategy classification, total P&L, key metrics
  - **Section 2: Market Universe** — crypto asset breakdown, market structure, coverage
  - **Section 3: Completeness Arbitrage** — spread analysis, matched vs unmatched shares
  - **Section 4: Execution Microstructure** — fill patterns, entry speed, slippage
  - **Section 5: Directional Edge** — tilt analysis, accuracy, one-sided markets
  - **Section 6: P&L Decomposition** — where the $713K comes from
  - **Section 7: Risk & Performance** — Sharpe, drawdown, win rate, capital efficiency
  - **Section 8: Bot Signature & Replication** — fingerprint, edge sustainability, capital requirements

- `main.py` (complete) — Full pipeline: `--skip-fetch` to skip collection, `--wallet` to change target, runs collection → analysis → synthesis → report

**Verify:** Open `output/report.html` in browser. All charts render. Findings are internally consistent. P&L decomposition sums to $713K (positions ground truth). Maker rebates ($40.7K) accounted for. Strategy conclusion is supported by quantitative evidence.

---

## Performance Guidelines (1.3M Records)

All analyzers must handle 1.3M trades without loading the full dataset into memory:

1. **SQL-first aggregation:** Compute per-condition_id rollups, daily summaries, and distributions in SQL. Only pull summary DataFrames into Python.
2. **Add helper queries to `database.py`:**
   - `per_market_summary()` → DataFrame with one row per condition_id (total buys/sells per outcome, VWAP, share counts, first/last timestamp)
   - `daily_summary()` → DataFrame with one row per day (trade count, volume, market count)
   - `market_fills(condition_id)` → DataFrame of all fills for a single market (for microstructure sampling)
3. **Batch processing:** For analyses that need per-market detail (execution microstructure), iterate over condition_ids in batches, don't load all 1.3M rows.
4. **Avoid the `seen` set pattern** in any new code — at 1.3M scale, in-memory dedup sets consume ~200MB+.

---

## Data Collection Status

| Dataset | Status | Records | Notes |
|---------|--------|---------|-------|
| Trades (TRADE) | COMPLETE | 1,323,832 | Full history Jan 19 – Feb 10 |
| Market metadata | COMPLETE | 8,313 | Via Gamma API `clob_token_ids` batches |
| Open positions | COMPLETE | 21 | Currently active positions |
| Closed positions | COMPLETE | 26,310 | P&L ground truth: $713K realized |
| Maker rebates | COMPLETE | 34 | $40,704 total rebates |

**All data collected.** Database: 762 MB, WAL checkpointed. Ready for Phase 3 analysis.

---

## API Reference (no auth required)

| Endpoint | Base URL | Use |
|----------|----------|-----|
| `GET /activity?user={wallet}&type=TRADE` | `data-api.polymarket.com` | All trade fills |
| `GET /activity?user={wallet}&type=MAKER_REBATE` | `data-api.polymarket.com` | Maker detection |
| `GET /positions?user={wallet}` | `data-api.polymarket.com` | Open positions |
| `GET /closed-positions?user={wallet}` | `data-api.polymarket.com` | Closed positions + P&L ground truth |
| `GET /markets?clob_token_ids=X&clob_token_ids=Y` | `gamma-api.polymarket.com` | Market metadata (array format, max ~75/batch) |

**Pagination:** No pagination metadata in responses. Detect end-of-data by `len(results) < limit`. Activity endpoint offset maxes at 3,000 — use backward timestamp windowing beyond that. Closed-positions caps at 50/page regardless of requested limit, but offset has no upper limit. Gamma API default limit=20, increase with `limit` param; URL length constrains batch size to ~75 tokens.

**Response format:** All endpoints return bare JSON arrays. Field names are camelCase. Data API numeric fields are actual JSON numbers. Gamma API returns `volume`/`liquidity`/`id` as strings (use `volumeNum`/`liquidityNum` instead). Gamma `outcomePrices`/`clobTokenIds`/`outcomes` are double-encoded JSON strings requiring `json.loads()`.

**Volume note:** Polymarket profile volumes are likely double-counted (per [Paradigm research, Dec 2025](https://www.paradigm.xyz/2025/12/polymarket-volume-is-being-double-counted)). The raw `usdcSize` sum from `/activity` ($20.5M) is the true single-counted USDC flow. Profile's "$86.8M" may reflect notional or double-counted volume.

## Dependencies
```
requests>=2.31.0
pandas>=2.1.0
numpy>=1.24.0
matplotlib>=3.8.0
plotly>=5.18.0
scipy>=1.11.0
tqdm>=4.66.0
```
