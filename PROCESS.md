# Process Log — Polymarket Bot Reverse Engineering

## Instructions for Future Self

**Read this file first.** It contains cumulative findings and decisions that prevent you from repeating work or making wrong assumptions. Key rules:

1. **Never load all trades into memory.** 1.3M rows = crash. Always use SQL aggregation via `database.py` helpers.
2. **Gamma API uses `clob_token_ids` (array format), NOT `condition_ids`.** The `condition_ids` param does fuzzy matching and returns wrong results.
3. **Closed-positions API caps at 50/page.** Must paginate with offset. No upper offset limit.
4. **Outcomes are "Up" and "Down", NOT "Yes" and "No".** These are crypto 15-min direction markets.
5. **P&L ground truth is $713,043** from closed-positions `realized_pnl`. Profile says ~$698K — close but not exact.
6. **The bot is NOT purely a taker.** $40,704 in maker rebates is real revenue.
7. **Position condition_ids (13,543) > trade condition_ids (8,314).** The wallet has history predating our trade window.
8. **Update this file after each phase.** Document findings, surprises, and decisions.

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

## Phase 3: Market Structure & Completeness Arbitrage — PENDING

*(will be filled after Phase 3 work)*

---

## Phase 4: Execution Microstructure — PENDING

---

## Phase 5: P&L and Performance — PENDING

---

## Phase 6: Temporal & Behavioral Patterns — PENDING

---

## Phase 7: Strategy Synthesis & Report — PENDING
