"""Polymarket bot analysis — main pipeline."""

import argparse
import os
import time

import config
from collectors.api_client import RateLimitedClient
from collectors.trade_collector import collect_trades
from collectors.market_collector import collect_markets
from collectors.position_collector import collect_positions
from storage.database import Database


def run_collection(db: Database, wallet: str, skip_fetch: bool = False):
    """Phase 2: Collect all data from Polymarket APIs into SQLite."""
    if skip_fetch:
        print("Skipping data collection (--skip-fetch)")
        print(f"  Existing trades: {db.trade_count()}")
        print(f"  Existing markets: {db.market_count()}")
        print(f"  Existing positions: {db.position_count()}")
        return

    client = RateLimitedClient()

    # Fixed cutoff so dataset doesn't grow during collection
    cutoff_ts = int(time.time())
    print(f"Collection cutoff: {cutoff_ts} (now)")

    # --- Trades ---
    print("\n[1/4] Collecting trades...")
    last_ts_str = db.get_metadata("last_trade_timestamp")
    start_ts = int(last_ts_str) if last_ts_str else None
    if start_ts:
        print(f"  Incremental mode: fetching trades after {start_ts}")

    count = collect_trades(
        client, db, wallet=wallet, activity_type="TRADE",
        start_ts=start_ts, end_ts=cutoff_ts,
    )
    if count:
        db.set_metadata("last_trade_timestamp", str(cutoff_ts))
    print(f"  Total trades in DB: {db.trade_count()}")

    # --- Maker rebates (small set, no pagination needed) ---
    print("\n[2/4] Collecting maker rebates...")
    collect_trades(
        client, db, wallet=wallet, activity_type="MAKER_REBATE",
        end_ts=cutoff_ts,
    )
    print(f"  Total MAKER_REBATE in DB: {db.trade_count('MAKER_REBATE')}")

    # --- Market metadata ---
    print("\n[3/4] Collecting market metadata...")
    # Get one asset (clob_token_id) per condition_id via SQL — avoids loading 1.3M rows
    asset_map = db.get_asset_per_condition_id()
    print(f"  Unique condition_ids with assets: {len(asset_map)}")

    markets = collect_markets(client, asset_map)
    if markets:
        db.upsert_markets(markets)
    print(f"  Total markets in DB: {db.market_count()}")

    # --- Positions ---
    print("\n[4/4] Collecting positions...")
    collect_positions(client, db, wallet=wallet)
    print(f"  Total positions in DB: {db.position_count()}")


def print_summary(db: Database):
    """Print a quick summary of collected data using SQL aggregation."""
    trade_count = db.trade_count()
    if trade_count == 0:
        print("\nNo trades found.")
        return

    stats = db.trade_summary_stats()

    print("\n" + "=" * 60)
    print("DATA COLLECTION SUMMARY")
    print("=" * 60)
    print(f"  Trades:          {trade_count:,}")
    print(f"  Maker rebates:   {db.trade_count('MAKER_REBATE'):,}")
    print(f"  Markets:         {db.market_count():,}")
    print(f"  Positions:       {db.position_count():,}")
    print(f"  Total volume:    ${stats['total_volume']:,.2f}")
    print(f"  Date range:      {stats['min_date']} to {stats['max_date']}")
    print(f"  Days active:     {stats['days_active']}")
    print(f"  Avg trades/day:  {trade_count / max(stats['days_active'], 1):,.1f}")
    print("=" * 60)


def run_phase3(db: Database):
    """Phase 3: Market Structure & Completeness Arbitrage."""
    from analyzers.market_structure import analyze_market_structure
    from analyzers.completeness import analyze_completeness

    print("\n" + "#" * 60)
    print("# PHASE 3: MARKET STRUCTURE & COMPLETENESS ARBITRAGE")
    print("#" * 60)

    pms = db.per_market_summary()
    print(f"\nPer-market summary: {len(pms):,} markets from trade data")

    structure = analyze_market_structure(db, pms)
    completeness = analyze_completeness(db, pms)

    return {'structure': structure, 'completeness': completeness}


def run_phase4(db: Database, phase3_result: dict):
    """Phase 4: Execution Microstructure & Sizing."""
    from analyzers.execution import analyze_execution
    from analyzers.sizing import analyze_sizing

    print("\n" + "#" * 60)
    print("# PHASE 4: EXECUTION MICROSTRUCTURE & CAPITAL DEPLOYMENT")
    print("#" * 60)

    pms = db.per_market_summary()
    completeness = phase3_result['completeness']

    execution = analyze_execution(db, pms, completeness)
    sizing = analyze_sizing(db, pms, completeness)

    return {'execution': execution, 'sizing': sizing}


def run_phase5(db: Database, phase3_result: dict, phase4_result: dict):
    """Phase 5: P&L Decomposition & Risk Metrics."""
    from analyzers.pnl import analyze_pnl
    from analyzers.risk import analyze_risk

    print("\n" + "#" * 60)
    print("# PHASE 5: P&L DECOMPOSITION & RISK METRICS")
    print("#" * 60)

    completeness = phase3_result['completeness']
    structure = phase3_result['structure']
    sizing = phase4_result['sizing']

    pnl = analyze_pnl(db, completeness, structure)
    risk = analyze_risk(pnl, sizing)

    return {'pnl': pnl, 'risk': risk}


def run_phase6(db: Database, phase3_result: dict, phase4_result: dict):
    """Phase 6: Temporal & Behavioral Patterns."""
    from analyzers.temporal import analyze_temporal

    print("\n" + "#" * 60)
    print("# PHASE 6: TEMPORAL & BEHAVIORAL PATTERNS")
    print("#" * 60)

    completeness = phase3_result['completeness']
    structure = phase3_result['structure']
    pms = db.per_market_summary()

    temporal = analyze_temporal(db, completeness, structure, pms)

    return {'temporal': temporal}


def run_phase7(db: Database, phase3: dict, phase4: dict,
               phase5: dict, phase6: dict):
    """Phase 7: Strategy Synthesis & Report."""
    from analyzers.strategy_synthesis import synthesize
    from reporting.report_generator import generate_report

    print("\n" + "#" * 60)
    print("# PHASE 7: STRATEGY SYNTHESIS & REPORT")
    print("#" * 60)

    synthesis = synthesize(phase3, phase4, phase5, phase6)
    report_path = generate_report(db, phase3, phase4, phase5, phase6, synthesis)

    return {'synthesis': synthesis, 'report_path': report_path}


def run_onchain_collection(db: Database, wallet: str,
                           skip_onchain: bool = False,
                           no_receipts: bool = False):
    """Collect on-chain OrderFilled events from Polygon."""
    if skip_onchain:
        count = db.onchain_fill_count()
        print(f"\nSkipping on-chain collection (--skip-onchain)")
        print(f"  Existing on-chain fills: {count:,}")
        return

    from collectors.onchain_collector import collect_onchain
    collect_onchain(db, bot_address=wallet, skip_receipts=no_receipts)


def run_phase8(db: Database, phase3: dict, phase4: dict):
    """Phase 8: On-chain analysis (maker/taker + counterparties)."""
    from analyzers.maker_taker import analyze_maker_taker
    from analyzers.counterparty import analyze_counterparties

    print("\n" + "#" * 60)
    print("# PHASE 8: ON-CHAIN MAKER/TAKER & COUNTERPARTY ANALYSIS")
    print("#" * 60)

    completeness = phase3['completeness']
    structure = phase3['structure']

    maker_taker = analyze_maker_taker(db, completeness, structure)
    counterparties = analyze_counterparties(db)

    return {'maker_taker': maker_taker, 'counterparties': counterparties}


def main():
    parser = argparse.ArgumentParser(description="Polymarket bot analysis pipeline")
    parser.add_argument("--wallet", default=config.WALLET_ADDRESS, help="Wallet address to analyze")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip data collection, use existing DB")
    parser.add_argument("--skip-onchain", action="store_true", help="Skip on-chain data collection")
    parser.add_argument("--no-receipts", action="store_true", help="Skip Pass 3 receipt fetches")
    args = parser.parse_args()

    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    db = Database()

    start = time.time()
    run_collection(db, wallet=args.wallet, skip_fetch=args.skip_fetch)
    elapsed = time.time() - start

    print_summary(db)
    print(f"\nCollection completed in {elapsed:.1f}s")

    # Phase 3: Analysis
    phase3_start = time.time()
    phase3 = run_phase3(db)
    print(f"\nPhase 3 completed in {time.time() - phase3_start:.1f}s")

    # Phase 4: Execution Microstructure
    phase4_start = time.time()
    phase4 = run_phase4(db, phase3)
    print(f"\nPhase 4 completed in {time.time() - phase4_start:.1f}s")

    # Phase 5: P&L Decomposition & Risk
    phase5_start = time.time()
    phase5 = run_phase5(db, phase3, phase4)
    print(f"\nPhase 5 completed in {time.time() - phase5_start:.1f}s")

    # Phase 6: Temporal & Behavioral Patterns
    phase6_start = time.time()
    phase6 = run_phase6(db, phase3, phase4)
    print(f"\nPhase 6 completed in {time.time() - phase6_start:.1f}s")

    # Phase 7: Strategy Synthesis & Report
    phase7_start = time.time()
    run_phase7(db, phase3, phase4, phase5, phase6)
    print(f"\nPhase 7 completed in {time.time() - phase7_start:.1f}s")

    # On-chain data collection
    onchain_start = time.time()
    run_onchain_collection(db, wallet=args.wallet,
                           skip_onchain=args.skip_onchain,
                           no_receipts=args.no_receipts)
    print(f"\nOn-chain collection completed in {time.time() - onchain_start:.1f}s")

    # Phase 8: On-chain analysis
    phase8_start = time.time()
    phase8 = run_phase8(db, phase3, phase4)
    print(f"\nPhase 8 completed in {time.time() - phase8_start:.1f}s")


if __name__ == "__main__":
    main()
