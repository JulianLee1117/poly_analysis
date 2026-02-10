"""Collect open and closed positions for a wallet."""

import time
from typing import List

from tqdm import tqdm

import config
from collectors.api_client import RateLimitedClient
from storage.database import Database
from storage.models import Position

# Closed-positions API caps at 50 per page regardless of requested limit
POSITIONS_PAGE_SIZE = 50
FLUSH_EVERY = 5000


def _parse_open_position(raw: dict) -> Position:
    """Convert an open position API record to a Position model."""
    return Position(
        asset=raw["asset"],
        condition_id=raw.get("conditionId", ""),
        outcome=raw.get("outcome", ""),
        size=float(raw.get("size", 0)),
        avg_price=float(raw.get("avgPrice", 0)),
        total_bought=float(raw.get("totalBought", 0) or 0),
        realized_pnl=float(raw.get("realizedPnl", 0) or 0),
        cur_price=float(raw.get("curPrice", 0) or 0),
        current_value=float(raw.get("currentValue", 0) or 0),
        initial_value=float(raw.get("initialValue", 0) or 0),
        cash_pnl=float(raw.get("cashPnl", 0) or 0),
        is_closed=False,
        opposite_outcome=raw.get("oppositeOutcome", ""),
        opposite_asset=raw.get("oppositeAsset", ""),
        end_date=raw.get("endDate", ""),
        close_timestamp=0,
        market_slug=raw.get("slug", ""),
        market_question=raw.get("title", ""),
    )


def _parse_closed_position(raw: dict) -> Position:
    """Convert a closed position API record to a Position model."""
    return Position(
        asset=raw["asset"],
        condition_id=raw.get("conditionId", ""),
        outcome=raw.get("outcome", ""),
        size=0.0,  # closed — no shares held
        avg_price=float(raw.get("avgPrice", 0)),
        total_bought=float(raw.get("totalBought", 0) or 0),
        realized_pnl=float(raw.get("realizedPnl", 0) or 0),
        cur_price=float(raw.get("curPrice", 0) or 0),
        current_value=0.0,  # closed
        initial_value=0.0,
        cash_pnl=0.0,
        is_closed=True,
        opposite_outcome=raw.get("oppositeOutcome", ""),
        opposite_asset=raw.get("oppositeAsset", ""),
        end_date=raw.get("endDate", ""),
        close_timestamp=int(raw.get("timestamp", 0) or 0),
        market_slug=raw.get("slug", ""),
        market_question=raw.get("title", ""),
    )


def collect_positions(
    client: RateLimitedClient,
    db: Database,
    wallet: str = config.WALLET_ADDRESS,
) -> int:
    """Fetch both open and closed positions with pagination.

    Returns total number of positions collected.
    """
    total = 0

    # --- Open positions (small set, single page) ---
    open_url = f"{config.DATA_API_BASE}/positions"
    open_data = client.get(open_url, params={"user": wallet}, skip_cache=True)

    if isinstance(open_data, list):
        open_positions = [_parse_open_position(raw) for raw in open_data]
        if open_positions:
            db.upsert_positions(open_positions)
            total += len(open_positions)
        print(f"  Open positions: {len(open_positions)}")

    # --- Closed positions (paginated, page_size=50 max) ---
    closed_url = f"{config.DATA_API_BASE}/closed-positions"
    offset = 0
    buffer: List[Position] = []

    pbar = tqdm(desc="Fetching closed positions", unit=" positions")

    while True:
        data = client.get(
            closed_url,
            params={"user": wallet, "limit": POSITIONS_PAGE_SIZE, "offset": offset},
            skip_cache=True,
        )

        if not isinstance(data, list):
            break

        for raw in data:
            buffer.append(_parse_closed_position(raw))
            pbar.update(1)

        # Flush buffer periodically
        if len(buffer) >= FLUSH_EVERY:
            db.upsert_positions(buffer)
            total += len(buffer)
            buffer.clear()

        if len(data) < POSITIONS_PAGE_SIZE:
            break

        offset += POSITIONS_PAGE_SIZE

    # Final flush
    if buffer:
        db.upsert_positions(buffer)
        total += len(buffer)
        buffer.clear()

    pbar.close()
    print(f"  Total positions collected: {total}")
    return total
