# Process Log — Polymarket Bot Reverse Engineering

## Instructions for Future Self

**Read this file first.** It contains cumulative findings and decisions that prevent you from repeating work or making wrong assumptions. Key rules:

1. **Never load all trades into memory.** 1.3M rows = crash. Always use SQL aggregation via `database.py` helpers.
2. **Gamma API uses `clob_token_ids` (array format), NOT `condition_ids`.** The `condition_ids` param does fuzzy matching and returns wrong results.
3. **Closed-positions API caps at 50/page.** Must paginate with offset. No upper offset limit.
4. **Outcomes are "Up" and "Down", NOT "Yes" and "No".** These are crypto 15-min direction markets.
5. **P&L ground truth is $713,043** from closed-positions `realized_pnl`. Trade-derived P&L is $281K for 8,310 resolved markets. The $432K gap decomposes: $254K from 5,587 pre-trade-window condition_ids + $178K methodological difference on overlapping markets (position API uses different avg_price than trade VWAP). (Prior $319K figure had survivorship bias — excluded one-sided losers.)
6. **The bot is NOT purely a taker.** $40,704 in maker rebates is real revenue. But `maker_address` is empty and `fee` is zero for ALL 1.3M trades — cannot classify maker/taker per fill.
7. **Position condition_ids (13,543) > trade condition_ids (8,314).** The wallet has history predating our trade window.
8. **Combined VWAP of $0.925 is misleading.** Only 32.4% of markets are well-balanced (shares within 20%). 27.7% have combined VWAP > $1.00 (timing mismatch, not error). Well-balanced markets: $0.940 combined. Must always tier by balance ratio.
9. **Sells are loss-cutting, NOT capital recycling.** 71% of sell fills are on losing outcomes, avg price $0.29, never above $0.65. Avg 3.7 min after first buy. Recovers 17.6% of buy capital ($2.2M of $12.6M).
10. **Spreads vary 4.3¢ by hour of day.** Widest at 2-3 UTC (9.8¢), tightest at 7 UTC (5.5¢). Peak volume at 14 UTC has WIDE spreads. Bot follows volume/volatility, not optimal spread windows.
11. **Join logic is solid.** `condition_id` links trades↔markets↔positions with 100% coverage. No need to parse clobTokenIds — `outcome` column already identifies the side.
12. **Update this file after each phase.** Document findings, surprises, and decisions.
13. **One-sided markets (4.4%) are execution failures, NOT directional alpha.** 42.7% accuracy (below random). P&L is -$427. All profit comes from both-sided completeness.
14. **All share-count and dollar tilt measures are biased by price asymmetry.** Share-weighted (41.4%) biased DOWN, dollar-weighted (68.4%) biased UP. The old "price-residual" test was algebraically identical to gross share count (S_u >= S_d) — prices cancel entirely, leaving the same downward bias. **Unbiased tests:** (a) Symmetric subset (|VWAP gap| < 5¢, n=701): agreement-adjusted null 49.7%, gross tilt 40.1%, z=-5.10 — anti-prediction. (b) Stratified permutation (shuffle outcomes within 20 price bins, 10K shuffles): observed gap +0.149 vs null mean +0.160, p=1.0 — bot allocates LESS toward winner than null. (c) Near-equal allocation: mean Up frac 0.4925 (std 0.1963). Conclusion: no directional prediction.
17. **Never compare tilt accuracy to 50%.** In these momentum markets, the cheaper side wins only 16.6% of the time (overall) or 46.4% (symmetric subset). Always compare to the agreement-adjusted null baseline, or use the stratified permutation test (shuffle outcomes within price bins to preserve price-outcome correlation).
18. **Permutation tests on allocation must be stratified by price.** Unstratified shuffle of outcome labels breaks the price-outcome correlation (expensive side wins ~83%), giving null mean ≈ 0 for dollar allocation gap — a false positive. Stratify by price_implied_up_frac (20 quantile bins) to preserve price-outcome link.
15. **Spreads EXPANDED over 22 days** (+5.34¢). First week 4.3¢, last week 9.6¢. Opposite of expected competition-driven compression. Phase 6: universal across all 4 assets (XRP widest +8.2¢, ETH +6.0¢). Positively correlated with fills/market over time (r=+0.45, p=0.033) — wider spreads come with more activity, not less.
16. **When determining market resolution, use BOTH cur_price=0 and cur_price=1.** Using only cur_price=1 creates survivorship bias on one-sided markets (misses losers whose only position resolved to 0).
19. **12% of markets are hourly, not 15-min.** 7,309 markets have "7:45AM-8:00AM" format (900s), 1,004 have "6PM" format (3600s). Market open = end_date minus duration. Use `_parse_market_duration()` in execution.py.
20. **Fill count has strong independent predictive power for balance** (r=+0.48 bivariate, t=41.5 in OLS controlling for log_volume). Multivariate OLS (R²=0.262): `log_fills` β=+0.127 (t=41.5), `is_hourly` β=+0.108 (t=13.0), `is_btc_eth` NOT significant (t=-1.4), `seq_gap` tiny (t=-3.3), `log_volume` negative (t=-8.3). **Causal interpretation is ambiguous**: `log_volume` (lifetime traded volume) is a poor proxy for instantaneous book depth at the moment of entry, so we cannot cleanly separate fill count from depth. But the fact that `log_fills` retains t=41.5 after the best available depth control suggests fill count likely has some independent causal role (more fills = more chances to rebalance). For replication: optimize BOTH market selection (depth) AND execution strategy (fill rate).
21. **BTC/ETH bivariate balance advantage (0.71-0.72 vs SOL/XRP 0.54-0.58) disappears in multivariate.** The advantage is fully explained by fill count and volume differences. `is_btc_eth` β=-0.011, t=-1.4. Don't recommend BTC/ETH over SOL/XRP for balance reasons alone.
22. **Hourly markets have genuinely independent balance advantage** (+10.8pp, t=13.0 controlling for fills). Not a fill-count proxy. More time = more opportunity windows to balance. This IS actionable for market selection.
23. **Sells genuinely improve balance, but cross-market comparison is selection-biased.** Cross-market: sell-markets 0.74 vs no-sell 0.60 (14.7pp, biased). Within-market: pre-sell 0.698 → post-sell 0.743 (true effect +4.5pp). Sells don't target the excess side (48.6%) but still improve net balance.
24. **Self-impact is NOT supported.** Drift/fill DECREASES with more fills (0.31x ratio: low $0.0082, high $0.0025). Consistent with random walk accumulation (σ√n), not self-impact. The 2.2x total drift difference was mechanical.
25. **Bot is scaling up over 22 days** (+82% daily buy volume, first week $569K → last week $1.03M). Peak concurrent exposure $292K, peak concurrent markets 113.
26. **Edge capture efficiency is entirely determined by balance.** Well-balanced markets: 59% mean capture, +$159 avg P&L. Very imbalanced: -124% capture, -$23 avg P&L.
27. **Market volume is NEGATIVELY associated with balance after controlling for fills** (β=-0.020, t=-8.3). Higher-volume markets have worse balance. Possible explanation: competitive pressure from other bots sweeping the same liquidity.
28. **P&L decomposition is algebraically exact.** Three components sum to trade_pnl with $0.000 max per-market error: (1) completeness spread = matched_pairs × (1 - combined_VWAP), (2) directional drag = unmatched × (resolution_price - excess_VWAP), (3) sell P&L = sell_proceeds - sell_shares × buy_VWAP per side. The decomposition values sold shares at their buy VWAP, creating a clean partition of total buy cost.
29. **Sell P&L requires two-layer framing: accounting loss vs economic impact.** Accounting sell loss is -$547K (57% of spread), but sell discipline offsets +$126K, giving net sell drag of -$421K (44% of spread). Directional drag from imbalance is -$134K (14%, no offset). Replication priority: (1) balance optimization via fills/depth (reduces BOTH drag and sell need), (2) sell timing refinement (reduces net sell drag). Selling is economically rational — 72% of sell-markets benefit.
30. **Hold-to-resolution counterfactual: $155K.** Without any sells, P&L drops from $281K to $155K. The $126K sell discipline value = sell_proceeds ($2.21M) - sold winning shares forfeited ($2.08M). Selling losers at $0.29 saves more than selling winners at $0.34 forfeits, because the 2.5:1 loser:winner sell ratio exceeds the breakeven ratio of 2.3:1.
31. **Reconciliation: `total_bought` is SHARES (proven algebraically).** Definitive test on 21,821 no-sell positions: `realized_pnl = total_bought × (cur_price - avg_price)` produces median residual $0.0000 (79% exact to $0.01). The USDC hypothesis (`pnl = total_bought × (cur_price/avg_price - 1)`) gives median residual $384 (0% exact). For losers, `pnl/total_bought` clusters at -0.29 (= -avg_price), not -1.0. With this proven, the fill gap is ~6% (pos/trade shares median 1.06), not the original "2.4x." The $178K P&L gap (position $459K vs trade $281K) is methodological (different avg_price), not missing fills.
32. **Bitcoin dominates P&L but this is from market depth, not an intrinsic BTC property.** BTC: $181K, 34% capture, 60% win rate. ETH: $71K, 27%. SOL: $19K, 18%. XRP: $10K, 17%. BTC/ETH have deeper books → more fills → better balance → higher capture. Phase 4 OLS: is_btc_eth t=-1.4 (not significant after controlling for fills). For replication: target depth, not asset.
33. **Sharpe 18 annualized is resolution-based, not mark-to-market.** P&L recognized at market close, so open-position exposure is invisible. High Sharpe confirms consistent arb execution, but does NOT indicate low real-time risk. More practical metric: max drawdown / peak exposure = ~4% (-$12K / $292K). 84% of days profitable. Calmar 375.
34. **Win rate 53.6% at market level** (4,259/7,945 both-sided). Well-balanced markets: 61.5% win, avg +$69. Very imbalanced: 36.8% win, avg -$38. Profit factor 1.31.
35. **Bot activity does NOT follow spread width.** Fills-spread hourly correlation r=-0.076, p=0.725 (not significant). Wide-spread hours (6 widest) avg 52.5K fills vs tight-spread hours (6 tightest) avg 52.2K — nearly identical. Verdict: market-cadence-driven automation. The 2.0x peak/quiet ratio is too flat for human scheduling — consistent with fully automated bot modulated by Polymarket's market creation rate (more markets during US hours), not an operator schedule.
36. **One-sided markets are confirmed late entries.** One-sided median entry speed 22s vs both-sided 8s (Mann-Whitney p=0.0000). 35.9% of one-sided markets enter after 60s vs 9.8% of both-sided. Avg capital deployed only $236 (vs $2,291 both-sided). XRP has highest one-sided rate (6.9%) confirming thinner liquidity.
37. **Sell trigger is price-based, not time-based. Two distinct mechanisms.** (a) Loss-cutting (58%): first sell below entry VWAP, avg 24% deterioration, median delay 264s. (b) Rebalancing (42%): first sell above entry VWAP (avg 1.32x), median delay 198s — selling excess winners faster. Overall: first sell price median $0.40, 99.3% below $0.50. Resolution accuracy scales with sell price: $0.00-0.20 → 90.7% sold a loser, $0.40-0.50 → 57.6%. The price distribution may reflect the natural price path of losing outcomes rather than a deliberate $0.40 threshold, but the monotonic resolution gradient confirms the signal is directionally correct for replication.
38. **Weekend activity is moderately reduced** (0.89x weekday fills). Suggests mostly automated with some human oversight — not pure 24/7 autonomy.
39. **Spread expansion is universal across all 4 assets.** XRP widened most (+8.2¢), ETH next (+6.0¢), BTC (+3.8¢), SOL (+3.4¢). Fills/market INCREASED (144 → 213) and entry speed IMPROVED (11.7s → 7.1s) during the same period. Wider spreads are NOT from reduced activity — the bot is getting better at execution while spreads widen (market conditions, not competition). **CAVEAT: 22-day window covers a single volatility regime.** Strategy profitability is partially conditional on continued crypto volatility maintaining wide spreads.

---

## Phase 1: Project Setup — COMPLETE

- SQLite + WAL mode, 762 MB database
- Rate-limited API client with file caching and exponential backoff
- Trade collector uses backward timestamp-windowed pagination (API offset caps at 3000)
- Models: Trade, Market, Position dataclasses

---

## Phase 2: Data Collection — COMPLETE

### What we collected

| Dataset | Records | Key fields |
|---------|---------|------------|
| Trades | 1,323,832 | tx_hash, asset, side, outcome, size, price, usdc_value, timestamp, condition_id |
| Markets | 8,313 | question, end_date, created_at, neg_risk, volume, liquidity, slug |
| Positions (open) | 21 | size, cur_price, current_value, cash_pnl, total_bought |
| Positions (closed) | 26,310 | cur_price (0 or 1), realized_pnl, total_bought, opposite_outcome/asset |
| Maker rebates | 34 | usdc_value (total $40,704) |

### Key findings from collection

- **Resolution split:** 13,158 winners (cur_price=1) vs 13,152 losers (cur_price=0) — 50.01%. Profit is NOT from picking winners; it's from the spread.
- **Maker rebates are significant:** 34 daily payouts averaging $1,197/day. Total $40,704 = ~5.7% of total P&L. Must include in P&L decomposition.
- **Market question format:** "Solana Up or Down - January 19, 7:45AM-8:00AM ET" — parse with regex to extract crypto asset + time window.
- **neg_risk = 0** for all sampled markets. These are simple binary markets, not multi-outcome negRisk bundles.
- **26,310 closed positions across 13,543 condition_ids** — ~1.94 per condition_id (one per outcome: Up + Down). The 13,543 > 8,314 gap means the bot traded ~5,229 markets before our Jan 19 trade window opened.

### Bugs fixed during Phase 2

1. **Memory crash:** `main.py` loaded all 1.3M trades into DataFrame to extract condition_ids. Fixed → SQL `SELECT DISTINCT condition_id`.
2. **Gamma API wrong param:** `condition_ids` comma-joined returns unrelated markets. Fixed → `clob_token_ids` array format.
3. **Position pagination missing:** Original collector made single API call. Actual closed positions = 26,310 at 50/page = 527 API calls.
4. **Position schema too thin:** Original had no `total_bought`, `cur_price`, `opposite_outcome`. Expanded with 9 new fields critical for P&L.

### Decisions made

- **Batch size 75 for Gamma API** — URL length constraint. Returns all 75 with `limit` param. 111 calls total.
- **Flush buffer every 5000 positions** to limit memory during collection.
- **Kept `load_trades()` and `load_all_trades()` in database.py** even though they shouldn't be used — removing would break existing code. Added warning in process doc instead.
- **Added `trade_summary_stats()` and `get_asset_per_condition_id()` SQL helpers** to database.py as first SQL-first aggregation methods.

---

## Pre-Phase-3 Data Investigation

Before starting analysis, investigated three concerns and the order-book-data question. Key findings that changed the plan:

### Order book snapshots: NOT needed
- `maker_address` is empty for all 1.3M trades — no per-fill maker/taker signal
- `fee` is zero for all trades — no fee-based signal either
- Price trajectory IS observable (early fills avg $0.487 vs late fills avg $0.424 — 6.3¢ decline), but cannot attribute to self-impact vs market movement
- **Decision:** Reframe all "slippage" as "price trajectory." Remove execution quality benchmarking. Add proxy analysis (compare high-fill vs low-fill markets for self-impact estimation).

### Capital recycling hypothesis: REFUTED
- User hypothesized: "bot sells winners at $0.90+ to free capital for next market"
- **Data shows opposite:** 71% of sell fills are on LOSING outcomes at avg $0.29. Zero sells above $0.65.
- Sells happen fast (3.7 min avg after first buy) and recover only 17.6% of buy capital ($2.2M of $12.6M)
- **Conclusion:** This is loss-cutting, not capital recycling. The bot dumps deteriorating positions at whatever price the market offers.
- **Decision:** Added sell analysis to Phase 4 and Phase 6. Reframed sell section from "capital recycling" to "loss-cutting discipline."

### Spread vs hour of day: CONFIRMED as meaningful
- Combined VWAP by hour: 4.3¢ range (5.5¢ at 7 UTC to 9.8¢ at 2-3 UTC)
- Peak fills at 14 UTC (US market open) has WIDE spreads — bot follows volatility, not optimal spread windows
- Bot IS active at all 24 hours (255-389 markets/hour) but with lower volume overnight
- **Decision:** Added spread-vs-hour cross-reference to Phase 6. Must test "operator schedule" vs "volatility-driven" hypotheses.

### VWAP distribution is bimodal — plan was wrong
- 27.7% of markets have buy-only combined VWAP > $1.00 — NOT errors, just timing mismatches
- 37.9% below $0.90 — genuinely cheap but includes imbalanced share counts
- Only 32.4% of markets are well-balanced (shares within 20%)
- Well-balanced markets: combined VWAP $0.940 (6¢ spread), vs $0.925 overall
- **Decision:** Phase 3 must tier markets by balance ratio. The headline $0.925 VWAP is misleading.

### P&L coverage gap discovered
- Trade-computed P&L: $319K (8,101 resolved markets)
- Position ground truth: $713K (13,543 condition_ids)
- Gap: $394K from 5,229 pre-Jan-19 condition_ids
- **Decision:** Phase 5 uses two P&L approaches — trade-derived for detailed decomposition, position-derived for total. Reconcile the overlap.

---

## Phase 3: Market Structure & Completeness Arbitrage — COMPLETE

### Files created
- `analyzers/__init__.py`
- `analyzers/market_structure.py` — crypto asset parsing, sidedness classification, one-sided accuracy
- `analyzers/completeness.py` — VWAP computation, balance tiers, matched pairs, P&L verification
- `database.py` addition: `per_market_summary()` — SQL aggregation returning one row per condition_id

### Key findings

**Market structure:**
- **4 crypto assets:** Bitcoin (29.3%), Ethereum (29.2%), Solana (20.8%), XRP (20.7%)
- **95.6% both-sided** (7,947 markets) — bot buys BOTH Up and Down in nearly every market. Completeness strategy confirmed.
- **4.4% one-sided** (366 markets: 164 up-only, 202 down-only) — XRP has the most (118), proportionally higher than other assets.
- **neg_risk = 0** for all 8,313 markets. Simple binary markets throughout.
- **Per-market volume:** mean $94,665, median $40,673. Wide range.

**Completeness arbitrage:**
- **Avg combined VWAP: $0.9287** → avg spread 7.13¢ per matched pair
- **Balance tiers (net shares after sells):**
  - Well-balanced (>0.80): 3,014 (37.9%) — VWAP $0.942, spread 5.8¢, 8.9M matched pairs
  - Moderate (0.50-0.80): 2,750 (34.6%) — VWAP $0.920, spread 8.0¢, 4.3M matched
  - Imbalanced (0.33-0.50): 949 (11.9%) — VWAP $0.916, spread 8.4¢, 610K matched
  - Very imbalanced (<0.33): 1,234 (15.5%) — VWAP $0.925, spread 7.5¢, 325K matched
- **14.17M total matched pairs, 5.13M unmatched shares**
- **Theoretical guaranteed profit: $962K** (matched pairs × spread per market)
- **Actual trade-derived P&L: $281K** — the $681K gap is directional losses on unmatched shares (41.4% accuracy) and sell losses

**Directional edge: NONE (confirmed via multiple unbiased tests)**
- **One-sided accuracy: 42.7%** (156/365 correct). BELOW random. P&L: -$427. One-sided markets are execution failures, not alpha.
- **Biased tilt measures (for reference only):** Net share 41.4% (DOWN bias), gross share 32.7% (DOWN bias — algebraically identical to the old "price-residual"), dollar 68.4% (UP bias). All biased by price asymmetry.
- **Unbiased tests:**
  - **Symmetric subset** (|VWAP gap| < 5¢, n=701): agreement-adjusted null 49.7%, gross tilt 40.1%, z=-5.10. Bot does WORSE than null (anti-prediction), consistent with equal-dollar buying noise.
  - **Stratified permutation** (shuffle outcomes within 20 price bins, 10K shuffles): observed gap +0.149 vs null mean +0.160, p=1.0. Bot allocates LESS toward winner than a zero-prediction buyer.
  - **Overall allocation:** mean Up frac 0.4925 (std 0.1963). Near-equal dollar split.
  - **Null context:** Cheaper side wins only 16.6% overall (momentum markets). All share-count measures must be compared to this null, not 50%.
- **All profit comes from the completeness spread.** The bot has no directional model.

**Spread evolution:**
- First week avg spread: 4.26¢
- Last week avg spread: 9.60¢
- **Trend: EXPANDING (+5.34¢)** — opposite of expected compression from competition. Possible explanations: market conditions changed, bot shifted to wider-spread opportunities, or less competition in later period.

**Sell impact:**
- 3,034 markets with sells (38.2% of both-sided)
- Total sell proceeds: $2,208,941
- Recovery rate: 17.6% of buy cost in affected markets

### Bugs found and fixed

1. **Survivorship bias in resolution detection:** Original approach used only `cur_price=1` positions to identify winners. For one-sided markets where the bot's only position LOST (cur_price=0), no winner record existed → market silently excluded. This made one-sided accuracy appear 100% (156/156) when the real figure is 42.7% (156/365). Fixed by deriving winning outcome from BOTH cur_price=0 and cur_price=1 positions.
2. **Trade-derived P&L corrected:** $319K → $281K after including one-sided losers in resolved set. The $38K difference was phantom profit from survivorship bias.

### Decisions made
- **`per_market_summary()` added to database.py** as the foundation for all analysis. Returns one row per condition_id with buy/sell costs/shares per outcome, computed via SQL GROUP BY on 1.3M trades. Runs in <1 second.
- **Balance tiers use NET shares (after sells)**, not gross. This gives the true portfolio at resolution time.
- **Spread buckets use 5¢ increments** for the distribution histogram.
- **One-sided P&L included in total** even though it's essentially zero. Makes the accounting complete.

---

## Phase 4: Execution Microstructure — COMPLETE

### Files created
- `analyzers/execution.py` — sequencing, entry speed, price trajectory, sell patterns, balance correlations
- `analyzers/sizing.py` — per-market capital, edge capture efficiency, concurrent exposure, daily deployment
- `database.py` additions: `per_market_execution_detail()`, `price_trajectory_summary()`, `market_fills()`, `daily_summary()`

### Key findings

**Central question answered: What causes the 71% edge leakage?**
Fill count has strong independent predictive power for balance quality (r=+0.48 bivariate, t=41.5 in OLS after controlling for `log_volume`). Whether this is causal (more fills → more chances to rebalance) or confounded (both driven by instantaneous book depth, which `log_volume` poorly proxies) cannot be cleanly separated with available data. But `log_fills` retaining t=41.5 after the best available depth control suggests fill count likely has some independent causal role. For replication: optimize both market selection AND fill strategy. Multivariate OLS (R²=0.262): `is_hourly` genuinely independent (+10.8pp, t=13.0), `is_btc_eth` drops out (t=-1.4), `seq_gap` tiny (t=-3.3), `log_volume` negative (t=-8.3, possible competition effect).

**Sequencing (Up/Down buy order):**
- First side: Up 50.6% / Down 49.4% — no systematic preference
- Gap mean 75.2s, median 30s. 4.5% simultaneous, 39.4% moderate (10-60s)
- Gap → balance: r=-0.15 (significant but weak). By tercile: fast 0.69, mid 0.67, slow 0.59
- First side = excess side: 54.5% (barely above chance) — entering first only weakly predicts excess

**Entry speed:**
- Median 8 seconds from market open — very fast
- 68.2% enter within 5-15 seconds
- No difference between 15-min (8s) and hourly (9s) markets
- Entry speed → balance: r=-0.10 (negligible)

**Execution duration:**
- Median 722s (12 min), mean 935s
- 54.7% span 10-15 minutes — bot uses most of the 15-min window
- Duration → balance: r=+0.42 (longer execution = better balance, because more fills)

**Price trajectory:**
- Up: first-5 avg $0.486 → last-5 $0.441 (drift -4.5¢)
- Down: first-5 avg $0.484 → last-5 $0.464 (drift -2.0¢)
- High-fill markets have 2.2x total drift — but drift/fill DECREASES (0.31x: low $0.0082, high $0.0025)
- **Self-impact NOT supported**: drift pattern consistent with random walk accumulation (σ√n), not price impact per fill
- Intra-market price range: avg $0.43 per outcome — massive variance within each market window

**Sell execution:**
- Sell delay: mean 219s (3.7 min), median 178s, at 33% of execution window
- Up/Down sell split: balanced (74K up / 76K down fills)
- Cross-market: sell-markets 0.74 vs no-sell 0.60 (14.7pp, SELECTION-BIASED — sell-markets are higher-fill)
- Within-market (causal): pre-sell 0.698 → post-sell 0.743 (genuine +4.5pp improvement)
- Sells don't target excess side specifically (48.6%) — improvement is indirect

**Balance correlations (KEY — what drives edge capture):**
| Feature | Bivariate r | OLS β | OLS t | Independent? |
|---------|-----------|-------|-------|--------------|
| log(fills) | +0.48 | +0.127 | +41.5 | **Yes** — dominant |
| is_hourly | — | +0.108 | +13.0 | **Yes** — genuine +10.8pp |
| is_btc_eth | — | -0.011 | -1.4 | **No** — fully explained by fills/volume |
| seq_gap | -0.15 | -0.00007 | -3.3 | Barely — 100s gap = -0.7pp |
| log(volume) | +0.28 | -0.020 | -8.3 | **Yes, negative** — competition effect? |
| Entry speed | -0.10 | — | — | Not included (negligible) |

**Balance by context (bivariate, not controlling for confounders):**
| Context | Avg Balance | Multivariate finding |
|---------|------------|---------------------|
| BTC/ETH | 0.71-0.72 | Advantage disappears controlling for fills |
| SOL/XRP | 0.54-0.58 | Lower fill count, not inherent disadvantage |
| Hourly markets | 0.79 | Genuine independent +10.8pp (t=13.0) |
| 15-min markets | 0.63 | Baseline |
| Q4 fill count | 0.81 | Strongest bivariate predictor |
| Q1 fill count | 0.47 | Low fills = low balance (both from thin books) |

**Capital deployment:**
- Per-market buy outlay: mean $2,291, median $1,146 (heavy-tailed)
- Total buy outlay: $18.2M, sell recovery: $2.2M, net: $16.0M
- Peak concurrent exposure: $292K, peak concurrent markets: 113
- Daily buy volume increasing +82% over 22 days (scaling up)
- Per-fill: mean $15.57 (small orders sweeping liquidity)

**Edge capture efficiency by balance tier:**
| Tier | Mean Capture | Avg P&L | n |
|------|-------------|---------|---|
| Well-balanced | 59% | +$159 | 2,186 |
| Moderate | 51% | +$102 | 2,017 |
| Imbalanced | -30% | -$5 | 652 |
| Very imbalanced | -124% | -$23 | 795 |

### Decisions made
- **Used SQL-first approach throughout.** `per_market_execution_detail()` computes per-outcome timestamps via SQL GROUP BY. `price_trajectory_summary()` uses window functions for first-5/last-5 avg prices. No per-market loading needed for main analysis.
- **Market duration parsed from question text** (15-min vs hourly). Market open = end_date - duration.
- **Balance ratio correlations use Spearman** (rank-based, robust to outliers) instead of Pearson.
- **Dropped formal "balance ratio prediction model"** from plan — simple correlations are sufficient and more interpretable.
- **Deprioritized burst detection** — doesn't directly answer edge leakage question.

---

## Phase 5: P&L and Performance — COMPLETE

### Files created
- `analyzers/pnl.py` — P&L decomposition, reconciliation, sell counterfactual, win/loss stats, by-asset, daily P&L
- `analyzers/risk.py` — Sharpe, drawdown, Calmar, loss streaks, tail risk, capital efficiency
- `database.py` addition: `position_pnl_by_condition()` — per-condition_id P&L from positions table

### Key findings

**P&L decomposition (exact, error $0.000):**
| Component | Amount | % of Spread |
|-----------|--------|------------|
| 1. Completeness spread | +$962,452 | 100% (theoretical) |
| 2. Directional drag | -$134,105 | 13.9% |
| 3. Sell P&L | -$547,366 | 56.9% |
| **Trade-derived total** | **+$280,981** | **29.2%** |
| Maker rebates (separate) | +$40,704 | 4.2% |

**Directional drag breakdown:**
- Excess on winner: 3,286 markets, +$865K (bonus profit)
- Excess on loser: 4,659 markets, -$999K (loss)
- By tier: well-balanced -$3K, moderate -$55K, imbalanced -$40K, very imbalanced -$36K

**Sell discipline counterfactual:**
- Hold-to-resolution P&L: $155,250
- Actual P&L (with sells): $280,981
- Sell discipline value: +$125,731 → selling IMPROVED returns
- Per-market: 72% of sell-markets benefited, 28% were hurt
- Winning shares sold: 2.08M (forfeited resolution payout)
- Losing shares sold: 5.31M (avoided worthless holds)

**Reconciliation (trade-derived vs position-derived):**
- 7,945 overlapping markets: trade $281K vs position $459K ($178K gap)
- `total_bought` is SHARES (proven): algebraic test on 21,821 no-sell positions — shares hypothesis median residual $0.0000 (79% exact), USDC hypothesis $384 (0% exact)
- Fill gap ~6% (pos/trade shares median 1.06), not the original "2.4x" (which was shares÷USDC)
- P&L gap is methodological (position API uses different avg_price), not missing fills
- Pre-trade-window P&L: $254K (5,587 condition_ids)
- Position ground truth total: $713,043

**Net sell drag framing:**
- Accounting sell loss: -$547K (57% of spread)
- Sell discipline offset: +$126K (selling improved vs hold)
- Net sell drag: -$421K (44% of spread — the avoidable portion)
- Directional drag: -$134K (14%, no offset — pure balance cost)
- Replication priority: (1) balance/depth, (2) sell timing

**Risk metrics:**
- Sharpe: 18 annualized — RESOLUTION-BASED, not mark-to-market (confirms consistent arb, not low real-time risk)
- Max drawdown: -$12,378
- Drawdown / peak exposure: ~4% (-$12K / $292K) — more practical risk metric
- Calmar: 375
- Max loss streak: 15 consecutive markets
- Max win streak: 19 consecutive markets
- Tail: p5 = -$557, p1 = -$1,554
- Capital efficiency: 733% trade P&L / avg exposure

**By-asset P&L:**
| Asset | P&L | Win Rate | Capture |
|-------|-----|----------|---------|
| Bitcoin | +$180,680 | 60.3% | 34% |
| Ethereum | +$71,130 | 54.5% | 27% |
| Solana | +$19,430 | 46.4% | 18% |
| XRP | +$9,742 | 49.9% | 17% |

**Daily P&L (56 days, all positions):**
- Avg: $12,733/day, 84% of days profitable
- Best day: $49,009, Worst day: -$12,378
- First week: $259, Last week: $167,642 (scaling up)

### Decisions made
- **Reused resolved_df from completeness.py** — no P&L recomputation. Added decomposition columns only.
- **Three-component decomposition** uses buy-only VWAPs to value all share categories (matched, held unmatched, sold). Algebraically exact partition of total buy cost.
- **Position-level daily P&L** uses close_timestamp for timing (when markets resolved). Covers all 13,532 condition_ids for the full $713K cumulative curve.
- **Capital efficiency** uses trade-derived P&L against trade-window exposure (apples to apples), not position P&L against partial exposure.
- **Reconciliation discrepancy investigated and proven.** Algebraic test on 21,821 no-sell positions definitively shows `total_bought` is shares (residual $0.0000) not USDC (residual $384). Fill gap ~6%, P&L gap ($178K) is methodological. Trade decomposition covers ~94% of fills.

---

## Phase 6: Temporal & Behavioral Patterns — COMPLETE

### Files created
- `analyzers/temporal.py` — hour-of-day, spread-vs-hour, day-of-week, one-sided timing, sell triggers, spread expansion decomposition
- `database.py` additions: `hourly_activity()`, `day_of_week_activity()`, `sell_detail_by_market()`

### What was pruned (already covered in Phases 3-5)
- Ramp-up/ramp-down → sizing.py (+82% daily volume)
- Tilt cause analysis → execution.py OLS (R²=0.262, fills dominant)
- Tilt cost quantification → pnl.py drag by tier, sizing.py edge capture by tier
- Sell impact on balance → execution.py within-market +4.5pp
- Session detection → bot runs 24/7 (low value)
- Market skip analysis → requires unavailable full market universe

### Key findings

**Hour-of-day activity:**
- Peak: 14:00 UTC (76K fills, US market open). Quiet: 22:00 UTC (39K fills)
- Peak/quiet ratio only 2.0x — bot is active all 24 hours
- Activity tracks volatility/volume, not spread opportunity

**Spread-vs-hour (CRITICAL test):**
- Fills-spread hourly correlation: r=-0.076, p=0.725 (NOT significant)
- Wide-spread hours: avg 52.5K fills. Tight-spread hours: avg 52.2K fills — nearly identical
- Verdict: **MARKET-CADENCE-DRIVEN AUTOMATION.** 2.0x peak/quiet ratio too flat for human scheduling. Bot fires on every new market regardless of spread, activity modulated by Polymarket's market creation rate.
- Implication for replication: hourly spread optimization could yield marginal improvement

**Day-of-week:**
- Weekend/weekday fill ratio: 0.89x (moderate reduction)
- Suggests mostly automated with some human oversight — not pure autonomy
- Mon peak (226K fills), Sat trough (171K fills)

**One-sided failure mode (confirmed: late entries):**
- One-sided entry speed: median 22s vs both-sided 8s (Mann-Whitney p<0.0001)
- Late entry (>60s): one-sided 35.9% vs both-sided 9.8% — 3.7x higher
- Avg capital: $236 one-sided vs $2,291 both-sided — bot commits less when uncertain
- XRP: 6.9% one-sided rate (highest), BTC: 3.8% (lowest) — confirms XRP thinner liquidity
- Mechanism: bot arrives late (after market open), one side's liquidity already consumed

**Sell trigger identification:**
- First sell price: median $0.40, 99.3% below $0.50
- **Two distinct mechanisms:**
  - Loss-cutting (58% of sell events): first sell below entry VWAP, avg 24% deterioration, median delay 264s
  - Rebalancing (42%): first sell above entry VWAP (avg 1.32x entry), median delay 198s — selling excess winners faster
- Resolution accuracy scales with sell price:
  - $0.00-0.20: 90.7% sold a loser (very confident signal)
  - $0.20-0.30: 73.6% sold a loser
  - $0.30-0.40: 66.5% sold a loser
  - $0.40-0.50: 57.6% sold a loser (near coin flip)
- Timing: median 236s delay, 40% happen 2-5 min after first buy
- Note: the ~$0.40 threshold may reflect the natural price path of losing outcomes rather than a deliberate rule, but the monotonic resolution gradient confirms the signal is directionally correct

**Spread expansion decomposition:**
- Universal across all 4 assets: XRP +8.2¢, ETH +6.0¢, BTC +3.8¢, SOL +3.4¢
- Fills/market INCREASED (144 → 213) — more execution, not less
- Entry speed IMPROVED (11.7s → 7.1s) — faster entry in later weeks
- Markets/day stable (341 → 327) — same opportunity set
- Daily spread-fills correlation: r=+0.447, p=0.033 — wider spreads come with more fills
- Conclusion: spread expansion is from market conditions (possibly higher crypto volatility), not reduced competition. The bot is executing better (faster entry, more fills) while spreads widen — favorable for the strategy.
- CAVEAT: 22-day window covers a single volatility regime. Strategy profitability is partially conditional on continued crypto volatility.

### Decisions made
- **Single file (`temporal.py`) instead of two** (temporal + imbalance). Remaining imbalance questions are behavioral/temporal in nature. The heavy imbalance analysis was already in execution.py.
- **Pruned 6 planned analyses** that were fully covered by Phases 3-5 to avoid redundancy.
- **Sell trigger uses first_sell_price** (not avg) for trigger analysis — the initial trigger is more informative than the average across subsequent fills.
- **Resolution accuracy by price bracket** confirms the sell rule is price-based: lower sell price = higher certainty of selling a loser.
- **No new SQL helpers needed for most analyses** — derived from existing per_market_summary and completeness results. Added 3 targeted helpers for hourly, day-of-week, and sell detail.

---

## Phase 7: Strategy Synthesis & Report — COMPLETE

### Files created
- `analyzers/strategy_synthesis.py` — cross-phase aggregator: strategy classification, headline metrics, bot fingerprint, replication feasibility
- `reporting/__init__.py` — package init
- `reporting/charts.py` — 13 Plotly chart functions (waterfall, cumulative P&L, spread/balance distributions, balance vs P&L scatter, per-asset P&L, spread evolution, hourly activity, spread by hour, capital deployment, edge capture by tier, entry speed, example market timeline)
- `reporting/report_generator.py` — self-contained HTML report with 8 sections, inline CSS, Plotly CDN, sticky TOC navigation
- `main.py` addition: `run_phase7()` wiring all phase results to synthesis + report

### What was changed from original plan
- `strategy_synthesis.py` slimmed from narrative-printing analyzer to lean cross-phase aggregator. All analysis already done in Phases 3-6; synthesis just organizes into report-friendly dict.
- Charts reduced from 16 to 13: dropped trade size distribution (low value); merged win rate into per-asset P&L; simplified day×hour heatmap to hour-of-day bar; added edge capture by balance tier (high value).
- Fixed entry_speed chart: column not in `sequencing_df` (computed after `seq` copy in execution.py). Fixed by deriving from `first_fill_ts - open_ts` in the chart function.
- Phase 5 return value now captured (`phase5 = run_phase5(...)`) — was previously discarded.

### Report structure (output/report.html)
- **Section 1: Executive Summary** — 8 metric cards, strategy description, central finding callout
- **Section 2: Market Universe** — asset distribution table, sidedness, one-sided failure note
- **Section 3: Completeness Arbitrage** — VWAP/spread metrics, balance tier table, spread + balance histograms, no-directional-model evidence
- **Section 4: Execution Microstructure** — entry speed, duration, sequencing, hourly activity, spread-vs-hour, automation verdict
- **Section 5: Edge Leakage** — waterfall chart (THE central chart), leakage component table, balance vs P&L scatter, edge capture by tier
- **Section 6: P&L Decomposition** — three-component table, sell discipline finding, cumulative P&L, per-asset P&L
- **Section 7: Risk & Performance** — Sharpe, drawdown, win/loss, streaks, tail risk
- **Section 8: Bot Signature & Replication** — fingerprint table, replication requirements, edge sustainability, regime caveat, data limitations
- **Appendix** — spread evolution, capital deployment, example market timeline

### Key outputs
- 545 KB self-contained HTML report at `output/report.html`
- 13 interactive Plotly charts embedded via CDN
- Full pipeline runs in ~19s total (0.5s for Phase 7)

### Decisions made
- **Plotly CDN (single include)** instead of embedding 3MB plotly.js per chart. Requires internet for chart rendering.
- **ScatterGL** for balance vs P&L (7,945 points) — WebGL rendering for performance.
- **Chart functions return None** on missing data instead of raising — graceful degradation.
- **No new database helpers needed** — all data available from existing phase results. Only exception: `db.market_fills()` for the example timeline.
- **Report is the primary output, not console printing.** Synthesis prints a brief summary; narrative goes in the HTML.
- **Tier labels use snake_case internally** (`well_balanced`) matching completeness.py, with display mapping to title case in charts and report.
