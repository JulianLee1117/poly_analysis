"""Collect all trades and maker rebates for a wallet."""

from typing import List, Optional, Set, Tuple

from tqdm import tqdm

import config
from collectors.api_client import RateLimitedClient
from storage.database import Database
from storage.models import Trade

FLUSH_EVERY = 10_000  # flush to DB every N new records to limit memory


def _parse_trade(raw: dict) -> Trade:
    """Convert a camelCase API record to a Trade model."""
    return Trade(
        transaction_hash=raw["transactionHash"],
        asset=raw.get("asset", ""),
        side=raw.get("side", ""),
        outcome=raw.get("outcome", ""),
        size=float(raw.get("size", 0)),
        price=float(raw.get("price", 0)),
        usdc_value=float(raw.get("usdcSize", 0)),
        timestamp=int(raw["timestamp"]),
        condition_id=raw.get("conditionId", ""),
        activity_type=raw.get("type", "TRADE"),
    )


def collect_trades(
    client: RateLimitedClient,
    db: Database,
    wallet: str = config.WALLET_ADDRESS,
    activity_type: str = "TRADE",
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
) -> int:
    """Fetch all trades using backward timestamp-windowed pagination.

    The API returns newest-first and has a hard offset limit of 3000.
    With limit=1000, we page offsets 0→3000 (4000 records per window),
    then set end=oldest_timestamp to slide the window backward.

    Flushes to DB every 10K records to limit memory usage.

    Returns the total number of new records collected.
    """
    base_url = f"{config.DATA_API_BASE}/activity"
    page_size = config.PAGE_SIZE
    max_offset = config.MAX_OFFSET

    seen: Set[Tuple[str, str]] = set()
    buffer: List[Trade] = []
    total_collected = 0
    window_end_ts = end_ts  # fixed cutoff (or None for no upper bound)
    window_num = 0

    pbar = tqdm(desc=f"Fetching {activity_type}", unit=" records")

    while True:
        window_num += 1
        offset = 0
        window_oldest_ts: Optional[int] = None
        window_exhausted = False

        # offset=3000 with limit=1000 works — gives us 4000 records per window
        while offset <= max_offset:
            params = {
                "user": wallet,
                "type": activity_type,
                "limit": page_size,
                "offset": offset,
            }
            if window_end_ts is not None:
                params["end"] = window_end_ts
            if start_ts is not None:
                params["start"] = start_ts

            data = client.get(base_url, params=params, skip_cache=True)

            if not isinstance(data, list):
                # API error dict — stop this window
                break

            for raw in data:
                key = (raw["transactionHash"], raw.get("asset", ""))
                if key in seen:
                    continue
                seen.add(key)
                buffer.append(_parse_trade(raw))
                pbar.update(1)

                ts = int(raw["timestamp"])
                if window_oldest_ts is None or ts < window_oldest_ts:
                    window_oldest_ts = ts

            # Flush buffer periodically
            if len(buffer) >= FLUSH_EVERY:
                db.upsert_trades(buffer)
                total_collected += len(buffer)
                buffer.clear()

            if len(data) < page_size:
                window_exhausted = True
                break

            offset += page_size

        if window_exhausted or window_oldest_ts is None:
            break

        # Slide window backward
        window_end_ts = window_oldest_ts

    # Final flush
    if buffer:
        db.upsert_trades(buffer)
        total_collected += len(buffer)
        buffer.clear()

    pbar.close()
    print(f"  Collected {total_collected} {activity_type} records across {window_num} window(s)")
    return total_collected
