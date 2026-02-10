# Process Log — Polymarket Bot Reverse Engineering

## Instructions for Future Self

**Read this file first.** It contains cumulative findings and decisions that prevent you from repeating work or making wrong assumptions. Key rules:

1. **Never load all trades into memory.** 1.3M rows = crash. Always use SQL aggregation via `database.py` helpers.
2. **Gamma API uses `clob_token_ids` (array format), NOT `condition_ids`.** The `condition_ids` param does fuzzy matching and returns wrong results.
3. **Closed-positions API caps at 50/page.** Must paginate with offset. No upper offset limit.
4. **Outcomes are "Up" and "Down", NOT "Yes" and "No".** These are crypto 15-min direction markets.
5. **P&L ground truth is $713,043** from closed-positions `realized_pnl`. But **trade-derived P&L is only $281K** for 8,310 resolved markets. The $432K gap is from 5,229 pre-Jan-19 condition_ids that have positions but no trade data. (Prior $319K figure had survivorship bias — excluded one-sided losers.)
6. **The bot is NOT purely a taker.** $40,704 in maker rebates is real revenue. But `maker_address` is empty and `fee` is zero for ALL 1.3M trades — cannot classify maker/taker per fill.
7. **Position condition_ids (13,543) > trade condition_ids (8,314).** The wallet has history predating our trade window.
8. **Combined VWAP of $0.925 is misleading.** Only 32.4% of markets are well-balanced (shares within 20%). 27.7% have combined VWAP > $1.00 (timing mismatch, not error). Well-balanced markets: $0.940 combined. Must always tier by balance ratio.
9. **Sells are loss-cutting, NOT capital recycling.** 71% of sell fills are on losing outcomes, avg price $0.29, never above $0.65. Avg 3.7 min after first buy. Recovers 17.6% of buy capital ($2.2M of $12.6M).
10. **Spreads vary 4.3¢ by hour of day.** Widest at 2-3 UTC (9.8¢), tightest at 7 UTC (5.5¢). Peak volume at 14 UTC has WIDE spreads. Bot follows volume/volatility, not optimal spread windows.
11. **Join logic is solid.** `condition_id` links trades↔markets↔positions with 100% coverage. No need to parse clobTokenIds — `outcome` column already identifies the side.
12. **Update this file after each phase.** Document findings, surprises, and decisions.
13. **One-sided markets (4.4%) are execution failures, NOT directional alpha.** 42.7% accuracy (below random). P&L is -$427. All profit comes from both-sided completeness.
14. **Directional tilt: THREE measures needed, two are biased.** Share-weighted tilt (41.4%) is biased DOWN (cheaper side yields more shares, cheaper side more likely to lose). Dollar-weighted tilt (68.4%) is biased UP (expensive side costs more, expensive side more likely to win). **Price-residual tilt (32.7%) is the correct unbiased measure** — controls for market prices by asking whether the bot allocates beyond what VWAPs dictate. Bot targets near-equal dollar allocation (actual_up_frac 0.4925, price-implied 0.4939). Conclusion: no directional prediction.
17. **Never use share-weighted or dollar-weighted tilt accuracy alone.** Both are systematically biased in opposite directions by market price asymmetry. Always use the price-residual test (actual dollar fraction vs VWAP-implied fraction) to assess directional prediction.
15. **Spreads EXPANDED over 22 days** (+5.34¢). First week 4.3¢, last week 9.6¢. Opposite of expected competition-driven compression. Investigate in Phase 6.
16. **When determining market resolution, use BOTH cur_price=0 and cur_price=1.** Using only cur_price=1 creates survivorship bias on one-sided markets (misses losers whose only position resolved to 0).

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

**Directional edge: NONE (confirmed via three independent tests)**
- **One-sided accuracy: 42.7%** (156/365 correct). BELOW random. P&L: -$427. One-sided markets are execution failures, not alpha.
- **Tilt accuracy (three measures to avoid bias):**
  - Share-weighted: 41.4% — biased DOWN (cheaper side gets more shares, cheaper side loses more often)
  - Dollar-weighted: 68.4% — biased UP (expensive side costs more, expensive side wins more often)
  - **Price-residual: 32.7%** — UNBIASED (controls for market prices). This is the definitive test.
  - Bot targets near-equal allocation: actual dollar frac 0.4925, price-implied frac 0.4939 — virtually no deviation.
- **All profit comes from the completeness spread.** The bot has no directional model. The price-residual test definitively rules out prediction beyond market prices.

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

## Phase 4: Execution Microstructure — PENDING

---

## Phase 5: P&L and Performance — PENDING

---

## Phase 6: Temporal & Behavioral Patterns — PENDING

---

## Phase 7: Strategy Synthesis & Report — PENDING
