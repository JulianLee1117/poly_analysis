"""Collect market metadata from the Gamma API for all traded condition IDs."""

import json
from typing import List, Set

from tqdm import tqdm

import config
from collectors.api_client import RateLimitedClient
from storage.models import Market


def _parse_market(raw: dict) -> Market:
    """Convert a Gamma API market record to a Market model."""
    # outcomePrices and clobTokenIds are double-encoded JSON strings
    outcome_prices_raw = raw.get("outcomePrices", "")
    if isinstance(outcome_prices_raw, str) and outcome_prices_raw:
        try:
            outcome_prices_raw = json.loads(outcome_prices_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    tokens_raw = raw.get("clobTokenIds", "")
    if isinstance(tokens_raw, str) and tokens_raw:
        try:
            tokens_raw = json.loads(tokens_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    return Market(
        condition_id=raw.get("conditionId", raw.get("condition_id", "")),
        question=raw.get("question", ""),
        slug=raw.get("slug", ""),
        category=raw.get("category", ""),
        end_date=raw.get("endDate"),
        created_at=raw.get("createdAt"),
        active=bool(raw.get("active", True)),
        closed=bool(raw.get("closed", False)),
        volume=float(raw.get("volumeNum", 0) or 0),
        liquidity=float(raw.get("liquidityNum", 0) or 0),
        spread=float(raw.get("spread", 0) or 0),
        outcome_prices=json.dumps(outcome_prices_raw) if outcome_prices_raw else "",
        description=raw.get("description", ""),
        tokens=json.dumps(tokens_raw) if tokens_raw else "",
    )


def collect_markets(
    client: RateLimitedClient,
    condition_ids: Set[str],
) -> List[Market]:
    """Batch-fetch market metadata from Gamma API.

    Args:
        client: Rate-limited HTTP client.
        condition_ids: Set of condition IDs to look up.
    """
    base_url = f"{config.GAMMA_API_BASE}/markets"
    batch_size = config.MARKET_BATCH_SIZE

    # Remove empty strings
    ids = sorted(cid for cid in condition_ids if cid)
    all_markets: List[Market] = []
    seen_ids: Set[str] = set()

    batches = [ids[i:i + batch_size] for i in range(0, len(ids), batch_size)]

    for batch in tqdm(batches, desc="Fetching markets", unit=" batch"):
        params = {"condition_ids": ",".join(batch)}
        data = client.get(base_url, params=params)

        if not isinstance(data, list):
            continue

        for raw in data:
            cid = raw.get("conditionId", raw.get("condition_id", ""))
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                all_markets.append(_parse_market(raw))

    print(f"  Collected {len(all_markets)} markets from {len(ids)} condition IDs")
    return all_markets
