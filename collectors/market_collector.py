"""Collect market metadata from the Gamma API for all traded condition IDs."""

import json
from typing import Dict, List, Set

from tqdm import tqdm

import config
from collectors.api_client import RateLimitedClient
from storage.models import Market

# Gamma API returns max 20 by default; with limit param we can get more.
# URL length caps out around batch=75 (token IDs are ~77 chars each).
GAMMA_BATCH_SIZE = 75


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
        neg_risk=bool(raw.get("negRisk", False)),
        neg_risk_market_id=raw.get("negRiskMarketId", ""),
    )


def collect_markets(
    client: RateLimitedClient,
    asset_map: Dict[str, str],
) -> List[Market]:
    """Batch-fetch market metadata from Gamma API using clob_token_ids.

    Args:
        client: Rate-limited HTTP client.
        asset_map: {condition_id: asset} mapping — one token per market.
    """
    base_url = f"{config.GAMMA_API_BASE}/markets"

    # Sort assets for deterministic ordering
    assets = sorted(a for a in asset_map.values() if a)
    all_markets: List[Market] = []
    seen_ids: Set[str] = set()

    batches = [assets[i:i + GAMMA_BATCH_SIZE] for i in range(0, len(assets), GAMMA_BATCH_SIZE)]

    for batch in tqdm(batches, desc="Fetching markets", unit=" batch"):
        # Use array format: ?clob_token_ids=X&clob_token_ids=Y
        params = [("clob_token_ids", a) for a in batch]
        params.append(("limit", len(batch) + 10))  # safety margin

        try:
            data = client.get_with_params_list(base_url, params=params)
        except Exception as e:
            print(f"  Warning: batch failed ({e}), skipping {len(batch)} tokens")
            continue

        if not isinstance(data, list):
            continue

        for raw in data:
            cid = raw.get("conditionId", raw.get("condition_id", ""))
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                all_markets.append(_parse_market(raw))

    print(f"  Collected {len(all_markets)} markets from {len(assets)} token lookups")
    missing = set(asset_map.keys()) - seen_ids
    if missing:
        print(f"  Warning: {len(missing)} condition_ids not found in Gamma API")
    return all_markets
