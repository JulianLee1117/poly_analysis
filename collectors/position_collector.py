"""Collect open and closed positions for a wallet."""

from typing import List

import config
from collectors.api_client import RateLimitedClient
from storage.models import Position


def _parse_open_position(raw: dict) -> Position:
    """Convert an open position API record to a Position model."""
    return Position(
        asset=raw["asset"],
        condition_id=raw.get("conditionId", ""),
        outcome=raw.get("outcome", ""),
        size=float(raw.get("size", 0)),
        avg_price=float(raw.get("avgPrice", 0)),
        realized_pnl=float(raw.get("realizedPnl", 0) or 0),
        current_value=float(raw.get("currentValue", 0)),
        is_closed=False,
        market_question=raw.get("title", ""),
    )


def _parse_closed_position(raw: dict) -> Position:
    """Convert a closed position API record to a Position model.

    Closed positions have different schema: no size/currentValue,
    but have totalBought/realizedPnl/timestamp.
    """
    return Position(
        asset=raw["asset"],
        condition_id=raw.get("conditionId", ""),
        outcome=raw.get("outcome", ""),
        size=0.0,  # closed — no shares held
        avg_price=float(raw.get("avgPrice", 0)),
        realized_pnl=float(raw.get("realizedPnl", 0) or 0),
        current_value=0.0,  # closed — no current value
        is_closed=True,
        market_question=raw.get("title", ""),
    )


def collect_positions(
    client: RateLimitedClient,
    wallet: str = config.WALLET_ADDRESS,
) -> List[Position]:
    """Fetch both open and closed positions.

    Args:
        client: Rate-limited HTTP client.
        wallet: Wallet address to query.
    """
    all_positions: List[Position] = []

    # Open positions
    open_url = f"{config.DATA_API_BASE}/positions"
    open_data = client.get(open_url, params={"user": wallet}, skip_cache=True)

    if isinstance(open_data, list):
        for raw in open_data:
            all_positions.append(_parse_open_position(raw))
        print(f"  Open positions: {len(open_data)}")

    # Closed positions
    closed_url = f"{config.DATA_API_BASE}/closed-positions"
    closed_data = client.get(closed_url, params={"user": wallet}, skip_cache=True)

    if isinstance(closed_data, list):
        for raw in closed_data:
            all_positions.append(_parse_closed_position(raw))
        print(f"  Closed positions: {len(closed_data)}")

    print(f"  Total positions: {len(all_positions)}")
    return all_positions
