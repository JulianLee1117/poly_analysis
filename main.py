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
    all_trades_df = db.load_all_trades()
    condition_ids = set(all_trades_df["condition_id"].unique()) if not all_trades_df.empty else set()
    positions_df = db.load_positions()
    if not positions_df.empty:
        condition_ids.update(positions_df["condition_id"].unique())

    markets = collect_markets(client, condition_ids)
    if markets:
        db.upsert_markets(markets)
    print(f"  Total markets in DB: {db.market_count()}")

    # --- Positions ---
    print("\n[4/4] Collecting positions...")
    positions = collect_positions(client, wallet=wallet)
    if positions:
        db.upsert_positions(positions)
    print(f"  Total positions in DB: {db.position_count()}")


def print_summary(db: Database):
    """Print a quick summary of collected data."""
    trades_df = db.load_trades()
    if trades_df.empty:
        print("\nNo trades found.")
        return

    print("\n" + "=" * 60)
    print("DATA COLLECTION SUMMARY")
    print("=" * 60)
    print(f"  Trades:          {len(trades_df):,}")
    print(f"  Maker rebates:   {db.trade_count('MAKER_REBATE'):,}")
    print(f"  Markets:         {db.market_count():,}")
    print(f"  Positions:       {db.position_count():,}")

    total_volume = trades_df["usdc_value"].sum()
    print(f"  Total volume:    ${total_volume:,.2f}")

    min_dt = trades_df["datetime"].min()
    max_dt = trades_df["datetime"].max()
    print(f"  Date range:      {min_dt:%Y-%m-%d} to {max_dt:%Y-%m-%d}")

    days_active = (max_dt - min_dt).days + 1
    print(f"  Days active:     {days_active}")
    print(f"  Avg trades/day:  {len(trades_df) / max(days_active, 1):,.1f}")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Polymarket bot analysis pipeline")
    parser.add_argument("--wallet", default=config.WALLET_ADDRESS, help="Wallet address to analyze")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip data collection, use existing DB")
    args = parser.parse_args()

    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    db = Database()

    start = time.time()
    run_collection(db, wallet=args.wallet, skip_fetch=args.skip_fetch)
    elapsed = time.time() - start

    print_summary(db)
    print(f"\nCollection completed in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
