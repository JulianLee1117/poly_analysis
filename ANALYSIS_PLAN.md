# Polymarket Bot Analysis Plan

## Target
**Account:** Uncommon-Oat (`0xd0d6053c3c37e727402d84c14069780d360993aa`)
https://polymarket.com/@k9Q2mX4L8A7ZP3R
- 1,323,832 fills across 8,313 markets (15-min crypto Up/Down) | $20.5M USDC volume | $713K realized P&L | 22 days active (Jan 19 – Feb 10, 2026)
- Profile shows "13,508 predictions" (market-level count) and "$86.8M volume" (double-counted or notional per Paradigm research)
- 26,310 closed positions: 13,158 winners (cur_price=1) vs 13,152 losers (cur_price=0) — nearly perfect 50/50 resolution split
- $40,704 in maker rebates across 34 daily payouts — significant revenue source
- **Strategy hypothesis:** Completeness arbitrage on crypto 15-minute markets — buying both Up and Down outcomes at combined VWAP < $1.00, with directional tilt toward predicted winner. Active loss-cutting on deteriorating sides (71% of sells are losers at avg $0.29). Follows volume/volatility, not optimal spread windows.

---

## What the Data Reveals (pre-analysis profiling)

| Metric | Value | Implication |
|--------|-------|-------------|
| Total fills | 1,323,832 | Individual order fills, 99.85% are 1-fill-per-tx (not partial fills of large orders) |
| Unique markets | 8,313 | ~370/day ≈ 4 concurrent crypto assets across 96 daily 15-min windows |
| Outcomes | Only "Up" and "Down" | Exclusively crypto price-direction markets (BTC/ETH/SOL 15-min) |
| BUY/SELL split | 88.6% BUY / 11.4% SELL | **Sells are loss-cutting, not profit-taking.** 71% of sell fills are on losing outcomes, avg sell price $0.29, never above $0.65. Sells happen 3.7 min avg after first buy. |
| Up vs Down BUYs | 50.2% Up / 49.8% Down | No directional bias overall — buys both sides |
| Both-sided markets | 95.6% (7,947 of 8,313) | Buys BOTH Up and Down in nearly every market |
| Up-only / Down-only | 164 / 202 | Only 4.4% are purely directional bets |
| Avg combined VWAP | $0.9250 (Up+Down, buy-only) | **Misleading as headline stat** — only 32.4% of markets are well-balanced; balanced-only VWAP is $0.9402. Distribution is bimodal: 37.9% below $0.90, 27.7% above $1.00 |
| Avg trade size | $15.50 USDC | Small orders sweeping available liquidity |
| Trades/minute | 46.7 avg, 748 peak | High-frequency automated execution |
| Max trades/second | 109 | Burst-mode liquidity sweeping |
| Market duration | 88.2% under 15 min | Confirms 15-minute market windows |
| Market start times | Cluster at :00, :15, :30, :45 | Aligned to standard 15-min crypto market intervals |
| Hour-of-day peak | 10:00–19:00 UTC | Peak fills at 14 UTC (US open), but **spreads are WIDER at peak volume** (9.4¢ at 14h vs 5.5¢ at 7h). Bot follows volatility/volume, not optimal spreads. |
| Maker rebates | 34 payouts, $40,704 total | Significant maker activity — $1,197/day avg rebate changes the taker-only assumption |
| Closed positions | 26,310 (13,158 W / 13,152 L) | 50/50 win/loss on outcomes; P&L comes from spread, not direction |
| Realized P&L | $713,043 (positions) | Ground truth from closed-positions API, includes all settled markets |
| Sell pattern | Sells in 36.5% of markets (3,035) | Loss-cutting: sells recover 17.6% of buy capital ($2.2M of $12.6M). Avg ~50 sell fills per market, balanced across Up/Down outcomes. |
| P&L coverage gap | Trade-computed P&L = $281K vs $713K positions | Only 39% of realized P&L comes from markets in our trade window. 5,229 condition_ids in positions have no trade data (pre-Jan-19 history). Corrected from $319K after survivorship bias fix. |
| Intra-market price variance | Avg range $0.49 per outcome per market | Bot fills at wildly different prices within a single market window. Stddev $0.136. Cannot attribute to self-impact vs market movement without order book data. |
| Share balance | 32.4% well-balanced, 14.9% very imbalanced (3x+) | Avg balance ratio 0.635. Combined VWAP is misleading for imbalanced markets — must use matched-pair analysis. |

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

### Join integrity:
- `trades.condition_id` → `markets.condition_id`: **8,313/8,313 matched** (100% coverage)
- `trades.asset` = one of the two clobTokenIds in `markets.tokens` JSON array
- `trades.condition_id` → `positions.condition_id`: 8,101 of 8,313 have closed-position matches (212 still open or unmatched)
- `markets.tokens` field is stored as plain JSON array (NOT double-encoded in our DB), each with 2 token IDs — no parsing footgun
- **No need to parse clobTokenIds for the join** — `condition_id` is the primary key that links all three tables. The `asset` field is only needed if you want to map a specific fill to a specific outcome token ID, which `outcome` column already provides.

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
  - **Per-market completeness calculation (TWO passes — gross and net):** For each condition_id:
    - **Gross (buy-only):** VWAP_up, VWAP_down, gross shares per side
    - **Net (after sells):** net_up_shares = buy_up - sell_up, net_down_shares = buy_down - sell_down
    - Combined VWAP = VWAP_up + VWAP_down (cost of a matched pair before sells)
    - Matched pairs = MIN(net_up_shares, net_down_shares) — guaranteed-profit portion
    - Unmatched shares = excess on one side — directional exposure
    - Guaranteed spread = matched_pairs × (1.00 - combined_VWAP)
    - Directional exposure = unmatched_shares × VWAP_of_excess_side
  - **Share balance analysis (CRITICAL — naive combined VWAP is misleading):**
    - Balance ratio = MIN(shares) / MAX(shares) per market
    - Tier markets: well-balanced (>0.80), moderate (0.50-0.80), imbalanced (<0.50), very-imbalanced (<0.33)
    - Compute combined VWAP and spread separately per tier
    - **Known distribution:** 32.4% well-balanced (VWAP $0.940), 14.9% very imbalanced (3x+ skew)
    - 27.7% of markets have buy-only combined VWAP > $1.00 — these are NOT errors; they reflect timing mismatches where prices moved between Up and Down fills
  - **Spread distribution:** Histogram of (1.00 - combined_VWAP) per balance tier, NOT one global histogram
  - **Sell impact:** For the 3,035 markets with sells:
    - Recalculate net position and effective cost basis after sells
    - Quantify capital recovered ($2.2M total, 17.6% of buy outlay)
    - Classify sells: loss-cutting (71% on losers at avg $0.29) vs rebalancing (29% on winners at avg $0.34)
    - Timing: avg 3.7 min after first buy, at ~33% of execution window
  - **Evolution over time:** Is the average spread improving, degrading, or stable across the 22-day window? (competition signal)
  - **All SQL-based:** Use a CTE that computes per-condition_id aggregates, return summary DataFrame

**Verify — CONFIRMED:** Avg combined VWAP = $0.9287 (buy-only, all both-sided). Well-balanced only = $0.942. Distribution is bimodal. Trade-derived P&L = **$281K** for 8,310 resolved markets (corrected from $319K after fixing survivorship bias on one-sided losers). Total matched pairs = 14.17M. One-sided accuracy = 42.7% (NOT 100% — prior figure was survivorship bias). Tilt accuracy in both-sided = 41.4% (directional exposure hurts, not helps). Spreads expanding +5.34¢ over 22 days.

---

## Phase 4: Execution Microstructure Analysis

**Goal:** Reverse-engineer HOW the bot executes — fill patterns, timing, order flow, and position building within each 15-minute window.

**Data limitations (no order book snapshots):**
- `maker_address` is **empty for all 1.3M trades** — cannot identify maker/taker per fill
- `fee` is **zero for all trades** — no fee-based maker/taker signal
- We have $40.7K aggregate maker rebates but cannot assign them to specific fills
- **Price trajectory is observable but attribution is ambiguous:** early fills avg $0.487, late fills avg $0.424 — a 6.3¢ decline. Could be self-impact (walking the book), organic price movement, or strategic sequencing. Without BBO snapshots, we cannot separate these.
- **Reframe all "slippage" as "price trajectory"** — we measure the bot's fill prices over time, not execution quality vs a benchmark.

**Files to create:**
- `analyzers/execution.py` — Intra-market execution patterns:
  - **Fill timeline per market:** For each condition_id, sequence of (timestamp, side, outcome, price, size). Analyze:
    - Does the bot buy Up first, then Down? Or interleave? Or simultaneous?
    - Time from market open (:00/:15/:30/:45) to first fill (entry speed)
    - Time from first fill to last fill (execution duration)
    - Fill rate over the window (front-loaded, steady, or back-loaded?)
  - **Price trajectory within market (NOT slippage):** Track the bot's fill prices across a market window.
    - Avg price of first 5 fills vs last 5 fills per outcome — measures price drift during execution
    - Intra-market price range: avg $0.49 per outcome, stddev $0.136 — high variance
    - Caveat: cannot attribute to self-impact vs organic market movement without order book data
    - Proxy: compare price trajectory in high-fill markets (likely self-impact) vs low-fill markets (likely organic)
  - **Up vs Down sequencing:** Avg gap 75 seconds between first Up and first Down fill. Analyze:
    - Distribution of this gap — simultaneous (0-5s), fast (5-30s), slow (30s+)
    - Does the gap predict profitability? (longer gap = more price risk)
  - **Burst detection:** Identify concentrated fill clusters (>10 fills within 5 seconds) — these are single order sweeps consuming multiple resting orders
  - **Sell execution patterns:** The 3,035 markets with sells:
    - Avg 50 sell fills per market, starting 3.7 min after first buy (33% of execution window)
    - 71% of sells are on losing outcomes at avg $0.29, 29% on winners at avg $0.34
    - Sell timing relative to price movement — does the bot sell AFTER price deteriorates or preemptively?
  - Sample analysis on top-50 markets by trade count, then validate patterns hold across full dataset via SQL aggregates

- `analyzers/sizing.py` — Position sizing and capital deployment:
  - **Per-market capital deployed:** Total USDC spent per condition_id (buy - sell)
  - **Capital deployment distribution:** Histogram of per-market spend — is it uniform or heavy-tailed?
  - **Balance ratio per market:** up_cost / (up_cost + down_cost) — how tilted is the directional bet?
    - 0.50 = perfectly balanced completeness arb
    - 0.70+ or 0.30- = strong directional conviction
  - **Concurrent capital:** At any point in time, how much capital is locked in unresolved markets?
  - **Capital turnover analysis:**
    - Total buy outlay: $18.2M, sell recovery: $2.2M (17.6%), net deployed: $16.0M
    - Time from market resolution to next market entry (using position close_timestamp and trade timestamps)
    - Capital recycling rate: how quickly does freed capital appear in new positions?
    - **Note:** The user hypothesized "selling winners at $0.90+ to free capital faster" — data refutes this. Sells are loss-cutting at $0.20-$0.40, not profit-taking. The capital freed by selling (~$2.2M) is meaningful but modest.
  - **Daily capital deployment:** Total USDC deployed per day — is the bot scaling up, stable, or scaling down?
  - **Fill size patterns:** Distribution of individual fill sizes — constant, random, or strategic (e.g., larger early, smaller as liquidity thins)?

**Verify:** Entry speed distribution should show most markets entered within first 1-2 minutes. Balance ratio distribution should cluster near 0.50 (completeness) with a tail toward directional tilts. Sell timing should show loss-cutting pattern confirmed.

---

## Phase 5: P&L and Performance Analysis

**Goal:** Decompose where the bot's $713K profit comes from and measure the quality of its edge.

**Critical P&L coverage gap:** Trade-computed P&L is **~$281K** for 8,310 resolved markets in our trade window (corrected from $319K after fixing survivorship bias on one-sided market losers). The positions ground truth is $713K across ALL 13,543 condition_ids (including 5,229 pre-Jan-19 markets with no trade data). Analysis must acknowledge this gap — we can fully decompose $281K from trades, and use positions-only data for the remaining $432K.

**Files to create:**
- `analyzers/pnl.py` — Profit & loss decomposition:
  - **Per-market P&L (SQL-based, TWO approaches):**
    - **Approach 1 — Trade-derived (8,310 markets):** For each condition_id with trades AND resolution:
      - Total buy cost (Up + Down), total sell proceeds
      - Net shares held at resolution: up_shares_net, down_shares_net (buys - sells per outcome)
      - Resolution payout: winning_net_shares × $1.00
      - P&L = resolution_payout + sell_proceeds - total_buy_cost
      - Known total: **~$281K** (both-sided: $281K, one-sided: -$0.4K). Use BOTH cur_price=0 and cur_price=1 to determine resolution (see PROCESS.md rule 16).
    - **Approach 2 — Position-derived (13,543 condition_ids):** Use `realized_pnl` from positions table
      - Covers all markets including pre-trade-window history
      - Total: $713K
      - Per-condition_id P&L available for all closed positions
    - **Reconciliation:** For the 8,310 overlapping markets, compare trade-derived P&L vs position `realized_pnl`. Quantify and explain any per-market discrepancies.
  - **P&L decomposition into five components:**
    1. **Completeness spread:** matched_pairs × (1.00 - combined_VWAP) — the guaranteed arb profit
    2. **Directional P&L:** unmatched_shares × (resolution_price - entry_price) — the speculative component
    3. **Sell P&L:** sell_proceeds - cost_basis_of_sold_shares — typically negative (loss-cutting at $0.29 avg)
    4. **Sell discipline value (counterfactual):** For each sell fill, compute `resolution_value - sell_price`:
       - Sells on losers (71%, avg $0.29): resolution = $0.00, so selling saved $0.29/share vs holding to zero (positive value)
       - Sells on winners (29%, avg $0.34): resolution = $1.00, so selling forfeited $0.66/share upside (negative value)
       - Net = first-order value of loss-cutting discipline vs a pure hold-to-resolution strategy
       - This is distinct from component 3: sell P&L measures the accounting loss on sells, sell discipline value measures the counterfactual benefit of selling vs not selling
       - Implementation: SQL join of sell fills to positions `cur_price` (resolution), ~15 lines
    5. **Maker rebates:** $40.7K aggregate — attribute proportionally or report as separate line item
  - **Hold-to-resolution counterfactual:** Compute total portfolio P&L assuming NO sells ever occurred:
    - For each market with sells, replace sell proceeds with resolution value of those shares
    - Compare counterfactual P&L to actual P&L — the difference is the system-level value of the sell discipline
    - **Second-order capital redeployment effect:** The $2.2M recovered by selling funds additional arb trades. This effect is real but hard to precisely quantify because capital is fungible. Estimate qualitatively by checking if the bot is capital-constrained (concurrent exposure analysis from Phase 4's `sizing.py`): if exposure hits a flat ceiling, redeployment has marginal value at the ~7.5% spread rate; if exposure fluctuates with opportunity, the constraint is market availability, not capital
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

**Verify:** Trade-derived P&L should be ~$319K (NOT $713K). Position-derived P&L = $713K. The $394K gap must be acknowledged as pre-trade-window history. Decomposition components (1-3, 5) should sum to the trade-derived total for the 8,101 markets. Sell discipline value (component 4) is a counterfactual metric reported alongside, not added into the sum. Hold-to-resolution counterfactual P&L should be computable for all 3,035 markets with sells. Maker rebates ($40.7K) reported separately.

---

## Phase 6: Temporal & Behavioral Patterns

**Goal:** Identify when and why the bot trades, and detect any behavioral signals that reveal its decision-making logic.

**Files to create:**
- `analyzers/temporal.py` — Time-based patterns:
  - **Daily activity profile:** Trades per hour-of-day (UTC) — confirm US hours bias, identify exact active window
  - **Spread-vs-hour cross-reference (CRITICAL):** Combined VWAP by hour of day:
    - **Known finding:** Spreads vary 4.3¢ by hour. Widest at 2-3 UTC (9.8¢, late US evening). Tightest at 7 UTC (5.5¢).
    - Peak fills at 14 UTC (US market open) has WIDE spreads (9.4¢), NOT tight — bot follows volume/volatility, not optimal spread windows.
    - **Test two hypotheses:** (1) Bot trades when operator is awake (human schedule), vs (2) Bot trades when volatility creates fat spreads (systematic)
    - If spreads are tighter at 3am UTC and the bot doesn't bother → operator schedule. If bot trades at ALL hours but adjusts volume by spread width → systematic.
    - **Known data:** Bot IS active at all 24 hours (255-389 markets per hour), but fills drop at 22-23 UTC. This is more consistent with operator schedule + volatility interaction.
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
  - **Sell trigger identification:** In the 3,035 markets with sells:
    - **Known:** Avg 3.7 min after first buy, 33% of execution window. 71% on losers at $0.29, 29% on winners at $0.34. Balanced across Up/Down outcomes.
    - **Hypothesis CONFIRMED:** Bot sells the losing side early to recover partial capital. NOT selling winners for capital recycling.
    - Remaining questions: What triggers the sell decision? Price threshold? Time threshold? Comparison to the other side's price?
    - Does the sell outcome predict the market resolution? (If bot sells Up early, does Down usually win?)
    - Which side is sold relative to the tilt — does the bot sell the smaller (excess) side or the larger?

**Verify:** One-sided markets should show clear directional conviction with measurable accuracy. Tilt accuracy > 50% would prove the bot has a directional model beyond pure arb. Sell triggers should reveal systematic rules — likely price-based (sell when outcome price drops below a threshold).

---

## Phase 7: Strategy Synthesis & Report

**Goal:** Bring all analyzer outputs together into a coherent reverse-engineering conclusion and generate a visual report.

**Files to create:**
- `analyzers/strategy_synthesis.py` — Synthesize findings:
  - **Strategy decomposition:** Quantify the relative contribution of each profit source:
    1. Completeness arbitrage spread (guaranteed component)
    2. Directional prediction alpha (speculative component)
    3. Loss-cutting discipline (sell timing — recovers ~$2.2M in capital). Report both the raw sell P&L (negative) and the counterfactual sell discipline value (likely positive) from Phase 5. The gap between these two numbers is the key insight: sells look bad in isolation but improve system-level P&L.
    4. Capital redeployment multiplier: if Phase 4 concurrent exposure shows a capital ceiling, estimate the additional arb profit generated by recycled sell capital at the average spread rate
    5. Maker rebates ($40.7K — passive income component)
  - **Edge identification:** What gives this bot its edge?
    - Speed: how fast does it enter after market opens? (measurable from trade timestamps)
    - Coverage: trading ~370 markets/day across ~4 assets — does breadth explain the profit?
    - Model: does the directional tilt accuracy imply a price prediction model?
    - Loss management: does the sell discipline (cutting losers at $0.29) meaningfully improve returns vs hold-to-resolution?
    - **Cannot determine without order book data:** Whether the bot gets better prices than other participants, whether it provides or consumes liquidity per fill, or what the competitive landscape looks like.
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
  15. **Price trajectory** — fill prices over time within market windows (NOT slippage — no BBO benchmark)
  16. **Spread by hour of day** — combined VWAP by hour, overlaid with fill volume (volatility vs activity)

- `reporting/report_generator.py` — HTML report assembly:
  - **Section 1: Executive Summary** — strategy classification, total P&L, key metrics
  - **Section 2: Market Universe** — crypto asset breakdown, market structure, coverage
  - **Section 3: Completeness Arbitrage** — spread analysis, matched vs unmatched shares
  - **Section 4: Execution Microstructure** — fill patterns, entry speed, price trajectory, sell behavior
  - **Section 5: Directional Edge** — tilt analysis, accuracy, one-sided markets
  - **Section 6: P&L Decomposition** — $319K from trade data + $394K from pre-window positions = $713K total
  - **Section 7: Risk & Performance** — Sharpe, drawdown, win rate, capital efficiency
  - **Section 8: Bot Signature & Replication** — fingerprint, edge sustainability, capital requirements

- `main.py` (complete) — Full pipeline: `--skip-fetch` to skip collection, `--wallet` to change target, runs collection → analysis → synthesis → report

**Verify:** Open `output/report.html` in browser. All charts render. Findings are internally consistent. Trade-derived P&L sums to ~$319K for 8,101 resolved markets. Position-derived P&L = $713K total. Gap of $394K from pre-trade-window markets is clearly documented. Maker rebates ($40.7K) accounted for. Strategy conclusion is supported by quantitative evidence.

---

## Data Limitations (No Order Book Snapshots)

**What we have:** 1.3M trade fills with price, size, timestamp, side, outcome per fill. Position resolution data with P&L ground truth. Market metadata.

**What we cannot determine:**

| Missing Signal | Impact | Proxy Available? |
|---|---|---|
| Best bid/offer (BBO) at each fill | Cannot measure execution quality vs market | No — `maker_address` empty for all 1.3M trades, `fee` zero for all |
| Book depth / available liquidity | Cannot assess self-impact vs organic price movement | Partial — intra-market price trajectory (early vs late fills) shows 6.3¢ avg decline, but attribution ambiguous |
| Maker/taker classification per fill | Cannot determine if bot provides or consumes liquidity on each trade | Partial — $40.7K aggregate maker rebates confirm some making activity, but cannot assign to specific fills |
| Counterparty identity | Cannot map the competitive landscape | No |
| Resting order state pre-trade | Cannot assess market selection criteria (did bot pick wide-spread markets?) | Partial — combined VWAP distribution by hour shows spread varies 4.3¢, suggesting market selection does incorporate spread width |

**Why this doesn't block the analysis:** The core reverse-engineering question — "what strategy does this bot use and how profitable is it?" — is fully answerable from trade + position data. Completeness arbitrage profitability, directional tilt, sell discipline, temporal patterns, and P&L decomposition are all derivable. The order book gap only limits claims about *execution quality* (which we reframe as *execution patterns*) and *competitive dynamics*.

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
