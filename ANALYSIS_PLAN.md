# Polymarket Bot Analysis Plan

## Target
**Account:** Uncommon-Oat (`0xd0d6053c3c37e727402d84c14069780d360993aa`)
https://polymarket.com/@k9Q2mX4L8A7ZP3R
- 1,323,832 fills across 8,313 markets (15-min crypto Up/Down) | $20.5M USDC volume | $713K realized P&L | 22 days active (Jan 19 – Feb 10, 2026)
- Profile shows "13,508 predictions" (market-level count) and "$86.8M volume" (double-counted or notional per Paradigm research)
- 26,310 closed positions: 13,158 winners (cur_price=1) vs 13,152 losers (cur_price=0) — nearly perfect 50/50 resolution split
- $40,704 in maker rebates across 34 daily payouts — significant revenue source
- **Strategy (confirmed by Phase 3):** Pure completeness arbitrage on crypto 15-minute and hourly markets — buying both Up and Down outcomes at combined VWAP < $1.00 (~$0.929). **No directional model** — confirmed via: symmetric subset (n=701, z=-5.10 vs adjusted null), stratified permutation (p=1.0, observed gap below null), one-sided accuracy 42.7%, near-equal allocation (Up frac 0.4925). Captures only 29% of theoretical edge ($281K / $962K) due to execution imbalance on 5.13M unmatched shares. Active loss-cutting on deteriorating sides. Spreads expanding over time (+5.34¢). The engineering problem is execution balance, not price prediction.
- **Execution bottleneck (Phase 4):** Fill count has strong independent predictive power for balance (t=41.5 after controlling for `log_volume` as depth proxy). Causal vs confounded cannot be cleanly separated — `log_volume` is lifetime volume, not instantaneous depth — but the retention of signal after depth control suggests fill count likely has some independent causal role (more fills = more chances to rebalance). Multivariate OLS (R²=0.262): `is_hourly` genuinely independent +10.8pp (t=13.0), `is_btc_eth` NOT independent (t=-1.4), `seq_gap` negligible. Self-impact NOT supported (drift/fill decreasing 0.31x). Sells improve balance +4.5pp within-market (not 14.7pp cross-market). Entry speed median 8s. Bot scaling up +82% daily. Well-balanced: 59% capture/+$159 vs very imbalanced: -124%/-$23. Replication: optimize both market selection (hourly, deep books) AND fill strategy.
- **P&L decomposition (Phase 5):** Exact three-component decomposition (error $0.000): spread $962K + drag -$134K + sell P&L -$547K = $281K. Sell P&L is the largest leakage (57% of spread), not directional drag (14%) — but selling IMPROVED returns by $126K vs hold-to-resolution ($155K). Selling is economically rational: 2.5:1 loser:winner sell ratio exceeds 2.3:1 breakeven. Bitcoin leads ($181K, 34% capture). Sharpe 18.02 annualized, max drawdown only -$12K. Win rate 53.6%, profit factor 1.31. Reconciliation discrepancy: activity endpoint likely missing fills (position `total_bought` is 2.4x trade buy cost for 99.97% of markets). Position ground truth $713K stands.

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
| Up-only / Down-only | 164 / 202 | **Execution failures, NOT directional bets.** Phase 3: 42.7% accuracy (below random), P&L = -$427. XRP disproportionately affected (6.9% one-sided vs ~3-4% for others). |
| Avg combined VWAP | $0.9287 (Up+Down, buy-only) | **Misleading as headline stat** — bimodal distribution. Well-balanced (37.9%): $0.942. Moderate (34.6%): $0.920. Imbalanced (27.5%): $0.921. Spread ranges from -10¢ to 20¢+. |
| Edge capture efficiency | 29% ($281K actual / $962K theoretical) | The bot loses 71% of its theoretical completeness edge to directional drag on unmatched shares and sell losses. No prediction confirmed (symmetric z=-5.10, stratified perm p=1.0) — drag is pure execution noise. The engineering bottleneck is execution balance, not strategy. |
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

**Verify — CONFIRMED:** Avg combined VWAP = $0.9287 (buy-only, all both-sided). Well-balanced only = $0.942. Distribution is bimodal. Trade-derived P&L = **$281K** for 8,310 resolved markets (corrected from $319K after fixing survivorship bias on one-sided losers). Total matched pairs = 14.17M. One-sided accuracy = 42.7% (NOT 100% — prior figure was survivorship bias). Directional prediction: **none** — symmetric subset z=-5.10 vs adjusted null (anti-prediction), stratified permutation p=1.0 (bot below null), near-equal allocation (Up frac 0.4925). Biased reference measures: net share 41.4%, gross share 32.7%, dollar 68.4%. Spreads expanding +5.34¢ over 22 days.

---

## Phase 4: Execution Microstructure Analysis

**Goal:** Reverse-engineer HOW the bot executes and **identify what causes the 71% edge leakage** ($962K theoretical → $281K actual). Phase 3 proved the bot has no directional model (symmetric z=-5.10, stratified perm p=1.0, near-equal allocation) — all profit is completeness spread. The execution quality (how well it balances Up/Down shares) is the entire engineering problem.

**Central question:** What creates the 5.13M unmatched shares? Is it liquidity constraints (can't buy enough of one side), self-impact (bot's own orders move prices), timing (prices move between buying sides), or market selection (enters markets where one side is already expensive)?

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
  - **Up vs Down sequencing → balance impact (KEY):** Avg gap 75 seconds between first Up and first Down fill. Analyze:
    - Distribution of this gap — simultaneous (0-5s), fast (5-30s), slow (30s+)
    - **Does the gap predict balance ratio?** If longer gaps → worse balance, timing is the bottleneck. If gap doesn't matter, liquidity is the bottleneck.
    - Does buying Up first vs Down first affect which side ends up with excess shares?
  - **Burst detection:** Identify concentrated fill clusters (>10 fills within 5 seconds) — these are single order sweeps consuming multiple resting orders
  - **Sell execution patterns:** The 3,035 markets with sells:
    - Avg 50 sell fills per market, starting 3.7 min after first buy (33% of execution window)
    - 71% of sells are on losing outcomes at avg $0.29, 29% on winners at avg $0.34
    - Sell timing relative to price movement — does the bot sell AFTER price deteriorates or preemptively?
  - **Balance ratio prediction model:** What execution features predict well-balanced (profitable) vs imbalanced (leaky) markets?
    - Candidates: entry speed, sequencing gap, fill count, price trajectory, time-of-day, crypto asset
    - This is the most important sub-analysis — it identifies the bot's execution bottleneck
  - Sample analysis on top-50 markets by trade count, then validate patterns hold across full dataset via SQL aggregates

- `analyzers/sizing.py` — Position sizing and capital deployment:
  - **Per-market capital deployed:** Total USDC spent per condition_id (buy - sell)
  - **Capital deployment distribution:** Histogram of per-market spend — is it uniform or heavy-tailed?
  - **Balance ratio per market:** up_cost / (up_cost + down_cost) — how balanced is the execution?
    - 0.50 = perfectly balanced completeness arb
    - 0.70+ or 0.30- = execution imbalance (NOT directional conviction — Phase 3 proved no directional edge; symmetric z=-5.10, stratified perm p=1.0)
  - **Edge capture efficiency per market:** actual_pnl / theoretical_guaranteed_profit — what fraction of the available spread did the bot capture? Correlate with balance ratio, fill count, entry speed, etc.
  - **Concurrent capital:** At any point in time, how much capital is locked in unresolved markets?
  - **Capital turnover analysis:**
    - Total buy outlay: $18.2M, sell recovery: $2.2M (17.6%), net deployed: $16.0M
    - Time from market resolution to next market entry (using position close_timestamp and trade timestamps)
    - Capital recycling rate: how quickly does freed capital appear in new positions?
    - **Note:** Sells are loss-cutting at $0.20-$0.40, not profit-taking. The capital freed by selling (~$2.2M) is meaningful but modest.
  - **Daily capital deployment:** Total USDC deployed per day — is the bot scaling up, stable, or scaling down?
  - **Fill size patterns:** Distribution of individual fill sizes — constant, random, or strategic (e.g., larger early, smaller as liquidity thins)?

**Verify — CONFIRMED:** Entry speed median 8s (68% within 5-15s — much faster than predicted). Dollar balance ratio mean 0.49 (near-equal), balance ratio heavy-tailed toward imbalance (39.7% below 0.50). Bivariate: fill count r=+0.48, seq gap r=-0.15, market volume r=+0.28. **Multivariate OLS (R²=0.262)**: `log_fills` dominant (t=41.5), `is_hourly` genuinely independent +10.8pp (t=13.0), `is_btc_eth` drops out (t=-1.4, fully explained by fills/volume), `seq_gap` tiny (t=-3.3), `log_volume` negative (t=-8.3, competition?). Edge capture: well-balanced 59%/+$159, very imbalanced -124%/-$23. Self-impact NOT supported: drift/fill decreases with more fills (0.31x ratio), consistent with random walk. Sells: cross-market 14.7pp (selection-biased), within-market +4.5pp (genuine). Bot scaling up +82% daily volume. Peak concurrent exposure $292K.

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
    1. **Completeness spread:** matched_pairs × (1.00 - combined_VWAP) — the guaranteed arb profit. Phase 3 found: $962K theoretical.
    2. **Directional drag:** unmatched_shares × (resolution_price - entry_price) — NOT a speculative component but an execution cost. Phase 3 proved no directional model (symmetric z=-5.10, stratified perm p=1.0), so unmatched shares are a consistent drag on returns, not a source of alpha. This is the largest component of the 71% edge leakage.
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

**Verify — CONFIRMED:** Trade-derived P&L = **$280,981** for 7,945 resolved both-sided markets. Decomposition exact (error $0.000): spread $962,452 + drag -$134,105 + sell P&L -$547,366 = $280,981. **Sell P&L is the largest leakage** (57% of spread), not directional drag (14%) — corrects the plan's prediction of "moderately negative" sell P&L. Drag breakdown: excess on winner +$865K, excess on loser -$999K. Selling IMPROVED returns by $125,731 vs hold-to-resolution ($155K hold P&L). Perfect-balance counterfactual: $962K (3.4x actual). Position P&L = $713K. **Reconciliation discrepancy discovered:** position `total_bought` is systematically 2.4x trade buy cost (99.97% of markets), suggesting activity endpoint misses fills. Position P&L for overlapping 7,945 markets = $459K vs trade $281K. Pre-window = $254K. Maker rebates $40,704 reported separately. Sharpe 18.02, max DD -$12K, Calmar 375. Win rate 53.6%, profit factor 1.31. Bitcoin leads ($181K, 34% capture).

---

## Phase 6: Temporal & Behavioral Patterns — REVISED

**Goal:** Identify when and why the bot trades, and detect behavioral signals that reveal its decision-making logic. Focused on questions NOT already answered by Phases 3-5.

**Already covered (dropped from Phase 6):**
- Ramp-up/ramp-down → sizing.py section 5 (+82% daily buy volume)
- Tilt cause analysis (fill count, seq gap, asset, duration) → execution.py OLS R²=0.262
- Tilt cost quantification → pnl.py drag by tier, sizing.py edge capture by tier
- Sell impact on balance → execution.py within-market +4.5pp (genuine causal test)
- Sell timing relative to window → execution.py (3.7 min, 33% of window)
- Overall spread trend → completeness.py (+5.34¢ over 22 days)
- Session detection → bot runs 24/7 with minimal gaps (low insight value)
- Market skip analysis → requires unavailable full market universe

**File: `analyzers/temporal.py`** — Single focused file:
1. **Hour-of-day activity profile:** Fill volume, buy volume, market count by UTC hour. Identify peak/quiet hours, activity range.
2. **Spread-vs-hour cross-reference (CRITICAL):** Combined VWAP by hour overlaid with activity.
   - Test: fills-spread hourly correlation. Positive = spread-seeking (systematic). Negative/flat = operator schedule.
   - Compare wide-spread hours vs tight-spread hours activity levels.
   - Verdict: operator schedule, systematic, or mixed.
3. **Day-of-week pattern:** Weekend vs weekday ratio. Human oversight signal.
4. **One-sided failure timing:** Entry speed of one-sided vs both-sided markets (Mann-Whitney). Late entry rate by category. Capital deployed comparison. Per-asset one-sided rates.
5. **Sell trigger identification:** First sell price distribution, deterioration from entry (first_sell_price / buy_VWAP), sell delay distribution, price threshold analysis. Resolution accuracy by sell price bracket — confirms price-based loss-cutting.
6. **Spread expansion decomposition:** Per-asset spread trends, fills/market over time, entry speed over time, daily spread-fills correlation, markets/day trend.

**Verify:** Hour-of-day should reveal whether bot follows operator schedule or optimal spreads. One-sided markets should correlate with late entry. Sell trigger should show consistent price threshold (~$0.30). Spread expansion should decompose by asset.

---

## Phase 7: Strategy Synthesis & Report — REVISED

**Goal:** Bring all analyzer outputs together into a coherent reverse-engineering conclusion and generate a visual HTML report.

**Changes from original plan:**
- `strategy_synthesis.py` slimmed to cross-phase aggregation only — all analysis already done in Phases 3-6. No narrative reprinting; narrative lives in the report.
- Charts reduced from 16 to 13: dropped trade size distribution (low value); merged win rate into per-asset P&L chart; simplified day×hour heatmap to hour-of-day bar (no new SQL needed); added edge capture by balance tier (high value).
- Added `reporting/__init__.py` (missing from original plan).
- Report uses Plotly CDN (single include), self-contained HTML, no external dependencies.

**Files to create:**
- `analyzers/strategy_synthesis.py` — Lean cross-phase aggregator:
  - Collects key metrics from all phase results into a unified dict
  - Strategy classification, headline metrics, bot fingerprint, replication feasibility, data limitations
  - Prints brief console summary (report is the primary output)
  - Returns structured dict consumed by report generator

- `reporting/__init__.py` — Package init

- `reporting/charts.py` — 13 Plotly chart functions (each returns a Figure):
  1. **Edge leakage waterfall** — THE central chart: $962K → drag → sell → $281K
  2. **Cumulative P&L + daily bars** — dual-axis bar/line combo
  3. **Completeness spread distribution** — histogram of (1.00 - combined_VWAP)
  4. **Balance ratio distribution** — histogram of min/max share ratio
  5. **Balance ratio vs P&L** — scatter colored by balance tier
  6. **Per-asset P&L + win rate** — grouped bar with secondary axis for win rate
  7. **Spread evolution over time** — line with trendline showing +5.34¢ expansion
  8. **Hour-of-day activity** — bar chart of fills by UTC hour
  9. **Spread by hour of day** — dual-axis: fills bar + spread line (shows no correlation)
  10. **Capital deployment over time** — area chart of daily buy volume (+82% trend)
  11. **Edge capture by balance tier** — bar showing 59% → -124% gradient
  12. **Entry speed histogram** — distribution of market-open-to-first-fill time
  13. **Example market fill timeline** — scatter of fills within a single 15-min window

- `reporting/report_generator.py` — Self-contained HTML report:
  - **Section 1: Executive Summary** — metric cards + strategy description
  - **Section 2: Market Universe** — asset distribution table, sidedness, market types
  - **Section 3: Completeness Arbitrage** — spread + balance charts, tier table, no directional model evidence
  - **Section 4: Execution Microstructure** — entry speed, hourly activity, spread-vs-hour, automation verdict
  - **Section 5: Edge Leakage** — waterfall, balance vs P&L scatter, edge capture by tier, fill count driver
  - **Section 6: P&L Decomposition** — three-component breakdown, cumulative P&L, per-asset, sell discipline
  - **Section 7: Risk & Performance** — Sharpe, drawdown, win/loss stats, capital efficiency
  - **Section 8: Bot Signature & Replication** — fingerprint table, replication guide, regime caveat, data limitations

- `main.py` — Add `run_phase7()` wiring all phase results to synthesis + report

**Verify:** Open `output/report.html` in browser. All 13 charts render interactively. Findings internally consistent. Edge leakage waterfall: $962K → drag -$134K → sell -$547K → $281K = 29% capture. Strategy: pure completeness arbitrage, no directional model (z=-5.10, p=1.0).

---

## Phase 8: On-Chain Data Collection & Analysis

**Goal:** Fill 3 of 5 data gaps (maker/taker per fill, fee, counterparty identity) by collecting Polygon CTF Exchange `OrderFilled` events via on-chain data. The bot's `transaction_hash` (100% populated) links to these events.

**Files created:**
- `collectors/onchain_collector.py` — PolygonRPC client, topic hash auto-discovery, block range binary search, three-pass log collection (bot=maker, bot=taker, OrdersMatched), receipt follow-up, verification
- `analyzers/maker_taker.py` — Maker/taker split by fills/volume/side/asset/hour/tier, fee analysis, fee-adjusted P&L, maker rebate reconciliation, self-impact re-attribution
- `analyzers/counterparty.py` — Counterparty universe, HHI/Gini/top-N concentration metrics, repeat opponent analysis, bot vs human classification

**Files modified:**
- `config.py` — Polygon RPC URL, rate limit, CTF Exchange contract addresses
- `storage/models.py` — OnchainFill dataclass
- `storage/database.py` — onchain_fills table, upsert/count/join/summary methods
- `main.py` — `run_onchain_collection()`, `run_phase8()`, `--skip-onchain` and `--no-receipts` CLI args

**Collection approach:**
- Auto-discovers OrderFilled topic hash and contract address from a sample tx receipt (no hardcoded keccak256)
- Binary searches for block range covering all trades (~950K blocks at Polygon's ~2s/block)
- Three passes via `eth_getLogs` in 3,000-block batches: pass 1 (bot=maker), pass 2 (bot=taker), pass 3 (OrdersMatched + receipt follow-up)
- Flush to DB every 5,000 records, dedup via `(transaction_hash, log_index)` PK
- Default 2 req/s for public RPC, configurable via `POLYGON_RPC_URL` env var for paid providers

**Analysis outputs:**
- Maker/taker classification for every matched fill
- Per-fill fee amounts ($0 vs actual)
- Counterparty addresses and competitive landscape
- Fee-adjusted P&L decomposition (4 components: spread + drag + sell + fees)
- Self-impact re-attribution split by maker vs taker fills
- Concentration metrics: HHI, Gini, top-N shares
- Bot vs human counterparty classification

**Verification:**
1. Topic hashes auto-discovered from sample tx
2. Coverage: % of DB trades with on-chain match (expect 95%+)
3. Decode cross-check: on-chain amounts match DB usdc_value within $0.01
4. Maker rebate reconciliation: maker_volume × rebate_rate vs $40,704
5. Fee total sanity: 0-2% of $20.5M volume

---

## Data Limitations (Updated After Phase 8)

**What we have:** 1.3M trade fills with price, size, timestamp, side, outcome per fill. Position resolution data with P&L ground truth. Market metadata. **On-chain OrderFilled events with maker, taker, and fee per fill.**

**What we cannot determine:**

| Missing Signal | Impact | Proxy Available? |
|---|---|---|
| Best bid/offer (BBO) at each fill | Cannot measure execution quality vs market | No — would need order book snapshots |
| Book depth / available liquidity | Cannot assess self-impact vs organic price movement | Partial — intra-market price trajectory + maker/taker split from Phase 8 |
| ~~Maker/taker classification per fill~~ | ~~Cannot determine if bot provides or consumes liquidity~~ | **RESOLVED by Phase 8** — on-chain OrderFilled events |
| ~~Counterparty identity~~ | ~~Cannot map competitive landscape~~ | **RESOLVED by Phase 8** — on-chain maker/taker addresses |
| ~~Fee per fill~~ | ~~Cannot compute actual fee drag~~ | **RESOLVED by Phase 8** — on-chain fee field |
| Resting order state pre-trade | Cannot assess market selection criteria | Partial — combined VWAP distribution by hour shows spread varies 4.3¢ |

**Phase 8 closes 3 of 5 data gaps** from a single public source (Polygon RPC, no API key required).

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
| On-chain fills | PENDING | — | OrderFilled events from Polygon CTF Exchange |

**API data collected.** On-chain data pending first run. Database: 762 MB, WAL checkpointed.

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
