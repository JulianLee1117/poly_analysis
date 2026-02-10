"""On-chain data collector — fetches OrderFilled events from Polygon CTF Exchange.

Strategy: Fetch transaction receipts and decode OrderFilled events.
Public RPCs don't support historical eth_getLogs, but eth_getTransactionReceipt
works for any historical transaction. Uses batch JSON-RPC to fetch 50 receipts
per HTTP request.

Auto-discovers OrderFilled topic hash from a sample tx receipt.
"""

import time
from typing import List, Optional, Tuple

import requests

import config
from storage.database import Database
from storage.models import OnchainFill


# --- Polygon JSON-RPC client ---

class PolygonRPC:
    """Minimal JSON-RPC client with token-bucket rate limiting and retry."""

    def __init__(
        self,
        url: str = config.POLYGON_RPC_URL,
        rps: float = config.POLYGON_RPC_RATE_LIMIT,
        burst: int = config.POLYGON_RPC_BURST,
    ):
        self.url = url
        self.rps = rps
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
        })
        self._req_id = 0

    def _refill_tokens(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rps)
        self.last_refill = now

    def _wait_for_token(self):
        self._refill_tokens()
        if self.tokens < 1.0:
            wait_time = (1.0 - self.tokens) / self.rps
            time.sleep(wait_time)
            self._refill_tokens()
        self.tokens -= 1.0

    def call(self, method: str, params: list) -> dict:
        """Make a JSON-RPC call with retry and backoff."""
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._req_id,
        }

        last_exception = None
        for attempt in range(config.POLYGON_RPC_MAX_RETRIES):
            self._wait_for_token()
            try:
                resp = self.session.post(self.url, json=payload, timeout=30)

                if resp.status_code == 429:
                    wait = max(10, config.BACKOFF_BASE * (
                        config.BACKOFF_FACTOR ** attempt))
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if "error" in data:
                    err = data["error"]
                    code = err.get("code", 0)
                    msg = str(err.get("message", "")).lower()
                    if (code in (-32005, -32000, -32090)
                            or "rate limit" in msg
                            or "too many" in msg):
                        wait = max(10, config.BACKOFF_BASE * (
                            config.BACKOFF_FACTOR ** attempt))
                        time.sleep(wait)
                        continue
                    raise RuntimeError(f"RPC error: {err}")

                return data.get("result")

            except requests.exceptions.RequestException as e:
                last_exception = e
                wait = config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** attempt)
                time.sleep(wait)
                continue

        raise last_exception or RuntimeError(
            f"RPC call failed after {config.POLYGON_RPC_MAX_RETRIES} retries")

    def batch_call(self, calls: list) -> list:
        """Make a batch JSON-RPC call. Returns list of results in order."""
        payloads = []
        for i, (method, params) in enumerate(calls):
            self._req_id += 1
            payloads.append({
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": self._req_id,
            })

        last_exception = None
        for attempt in range(config.POLYGON_RPC_MAX_RETRIES):
            self._wait_for_token()
            try:
                resp = self.session.post(
                    self.url, json=payloads, timeout=120)

                if resp.status_code == 429:
                    wait = max(10, config.BACKOFF_BASE * (
                        config.BACKOFF_FACTOR ** attempt))
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if not isinstance(data, list):
                    # Some RPCs return error for batch
                    if isinstance(data, dict) and "error" in data:
                        wait = max(10, config.BACKOFF_BASE * (
                            config.BACKOFF_FACTOR ** attempt))
                        time.sleep(wait)
                        continue
                    return [None] * len(calls)

                # Sort by id to match original order
                id_map = {d.get("id"): d for d in data}
                results = []
                for p in payloads:
                    resp_item = id_map.get(p["id"], {})
                    results.append(resp_item.get("result"))
                return results

            except (requests.exceptions.RequestException, ValueError) as e:
                last_exception = e
                wait = config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** attempt)
                time.sleep(wait)
                continue

        raise last_exception or RuntimeError(
            f"Batch RPC failed after {config.POLYGON_RPC_MAX_RETRIES} retries")


# --- Hex decoding helpers ---

def _hex_to_int(h: str) -> int:
    """Convert hex string (with or without 0x) to int."""
    return int(h, 16) if h else 0


def _hex_to_address(h: str) -> str:
    """Convert 32-byte hex topic to 20-byte address (lowercase, checksumless)."""
    h = h.lower()
    if h.startswith("0x"):
        h = h[2:]
    return "0x" + h[-40:]


def _decode_uint256(hex_chunk: str) -> int:
    """Decode a 64-char hex chunk as uint256."""
    return int(hex_chunk, 16)


# --- Event decoding ---

def decode_order_filled(log: dict, bot_address: str) -> Optional[OnchainFill]:
    """Decode an OrderFilled event log into an OnchainFill.

    OrderFilled(
        bytes32 indexed orderHash,
        address indexed maker,
        address indexed taker,
        uint256 makerAssetId,
        uint256 takerAssetId,
        uint256 makerAmountFilled,
        uint256 takerAmountFilled,
        uint256 fee
    )

    Topics: [event_sig, orderHash, maker, taker]
    Data: makerAssetId(32) + takerAssetId(32) + makerAmount(32) + takerAmount(32) + fee(32)
    """
    topics = log.get("topics", [])
    if len(topics) < 4:
        return None

    data = log.get("data", "0x")
    if data.startswith("0x"):
        data = data[2:]

    # Need 5 × 64 = 320 hex chars minimum
    if len(data) < 320:
        return None

    order_hash = topics[1]
    maker = _hex_to_address(topics[2])
    taker = _hex_to_address(topics[3])

    maker_asset_id = str(_decode_uint256(data[0:64]))
    taker_asset_id = str(_decode_uint256(data[64:128]))
    maker_amount = _decode_uint256(data[128:192]) / 1e6
    taker_amount = _decode_uint256(data[192:256]) / 1e6
    fee = _decode_uint256(data[256:320]) / 1e6

    bot_addr = bot_address.lower()
    if maker == bot_addr:
        bot_role = "maker"
    elif taker == bot_addr:
        bot_role = "taker"
    else:
        return None  # Not a bot fill

    tx_hash = log.get("transactionHash", "")
    log_index = _hex_to_int(log.get("logIndex", "0x0"))
    block_number = _hex_to_int(log.get("blockNumber", "0x0"))

    return OnchainFill(
        transaction_hash=tx_hash,
        log_index=log_index,
        block_number=block_number,
        order_hash=order_hash,
        maker=maker,
        taker=taker,
        maker_asset_id=maker_asset_id,
        taker_asset_id=taker_asset_id,
        maker_amount=maker_amount,
        taker_amount=taker_amount,
        fee=fee,
        bot_role=bot_role,
    )


# --- Discovery ---

def discover_topic_hash(rpc: PolygonRPC, db: Database, bot_address: str
                        ) -> Tuple[str, str]:
    """Discover OrderFilled topic hash and contract address from a sample tx.

    Returns (order_filled_topic, contract_address).
    """
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT transaction_hash FROM trades "
            "WHERE activity_type='TRADE' LIMIT 1"
        ).fetchone()

    if not row:
        raise RuntimeError("No trades in DB — cannot discover topic hashes")

    sample_tx = row["transaction_hash"]
    print(f"  Discovering topics from sample tx: {sample_tx[:18]}...")

    receipt = rpc.call("eth_getTransactionReceipt", [sample_tx])
    if not receipt:
        raise RuntimeError(f"No receipt for tx {sample_tx}")

    logs = receipt.get("logs", [])
    ctf_addr = config.CTF_EXCHANGE_ADDRESS.lower()
    negrisk_addr = config.NEGRISK_CTF_EXCHANGE_ADDRESS.lower()

    order_filled_topic = None
    contract_address = None

    for log in logs:
        log_addr = log.get("address", "").lower()
        topics = log.get("topics", [])

        if log_addr in (ctf_addr, negrisk_addr) and topics:
            data = log.get("data", "0x")
            if data.startswith("0x"):
                data = data[2:]

            # OrderFilled has 4 topics and 320 hex chars of data (5 uint256)
            if len(topics) == 4 and len(data) >= 320:
                order_filled_topic = topics[0]
                contract_address = log_addr
                break

    if not order_filled_topic:
        # Broader search — check all logs for OrderFilled-like shape
        for log in logs:
            topics = log.get("topics", [])
            data = log.get("data", "0x")
            if data.startswith("0x"):
                data = data[2:]
            if len(topics) == 4 and len(data) >= 320:
                order_filled_topic = topics[0]
                contract_address = log.get("address", "").lower()
                break

    if not order_filled_topic:
        raise RuntimeError(
            f"Could not find OrderFilled event in receipt for {sample_tx}. "
            f"Receipt had {len(logs)} logs.")

    print(f"  OrderFilled topic: {order_filled_topic[:18]}...")
    print(f"  Contract address:  {contract_address}")

    return order_filled_topic, contract_address


# --- Receipt-based collection ---

def process_receipt(receipt: dict, bot_address: str,
                    order_filled_topic: str,
                    contract_address: str) -> List[OnchainFill]:
    """Extract OrderFilled events for the bot from a tx receipt."""
    fills = []
    if not receipt:
        return fills

    for log in receipt.get("logs", []):
        log_addr = log.get("address", "").lower()
        topics = log.get("topics", [])

        # Match contract and event topic
        if log_addr != contract_address:
            continue
        if not topics or topics[0] != order_filled_topic:
            continue

        fill = decode_order_filled(log, bot_address)
        if fill:
            fills.append(fill)

    return fills


def collect_via_receipts(
    rpc: PolygonRPC,
    db: Database,
    bot_address: str,
    order_filled_topic: str,
    contract_address: str,
    sample_size: int = 0,
) -> int:
    """Collect on-chain fills by fetching transaction receipts in batches.

    Args:
        sample_size: If >0, randomly sample this many txs. If 0, fetch all.

    Returns total fills collected.
    """
    # Get unique transaction hashes
    if sample_size > 0:
        query = (
            "SELECT DISTINCT transaction_hash FROM trades "
            "WHERE activity_type='TRADE' ORDER BY RANDOM() LIMIT ?"
        )
        with db._get_conn() as conn:
            rows = conn.execute(query, (sample_size,)).fetchall()
    else:
        query = (
            "SELECT DISTINCT transaction_hash FROM trades "
            "WHERE activity_type='TRADE'"
        )
        with db._get_conn() as conn:
            rows = conn.execute(query).fetchall()

    tx_hashes = [r["transaction_hash"] for r in rows]
    total_txs = len(tx_hashes)

    mode = f"sample of {sample_size:,}" if sample_size > 0 else "full census"
    print(f"\n  Collection mode: {mode}")
    print(f"  Transaction hashes to fetch: {total_txs:,}")

    batch_size = 50
    total_batches = (total_txs + batch_size - 1) // batch_size
    est_minutes = total_batches * 1.5 / 60  # ~1.5s per batch
    print(f"  Batches: {total_batches:,} (batch size {batch_size})")
    print(f"  Estimated time: ~{est_minutes:.0f} minutes")

    all_fills = []
    seen_keys = set()
    flush_threshold = 5000
    total_collected = 0
    start_time = time.time()

    for batch_idx in range(total_batches):
        batch_start = batch_idx * batch_size
        batch_end = min(batch_start + batch_size, total_txs)
        batch_hashes = tx_hashes[batch_start:batch_end]

        # Build batch RPC call
        calls = [
            ("eth_getTransactionReceipt", [tx])
            for tx in batch_hashes
        ]

        try:
            results = rpc.batch_call(calls)
        except Exception as e:
            # Fall back to individual calls
            results = []
            for tx in batch_hashes:
                try:
                    r = rpc.call("eth_getTransactionReceipt", [tx])
                    results.append(r)
                except Exception:
                    results.append(None)

        # Process receipts
        for receipt in results:
            fills = process_receipt(
                receipt, bot_address,
                order_filled_topic, contract_address)
            for f in fills:
                key = (f.transaction_hash, f.log_index)
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_fills.append(f)

        # Flush
        if len(all_fills) >= flush_threshold:
            db.upsert_onchain_fills(all_fills)
            total_collected += len(all_fills)
            all_fills = []

        # Progress
        if (batch_idx + 1) % 20 == 0 or batch_idx == total_batches - 1:
            elapsed = time.time() - start_time
            done = batch_end
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total_txs - done) / rate if rate > 0 else 0
            print(f"    {done:,}/{total_txs:,} txs "
                  f"({done/total_txs*100:.1f}%), "
                  f"{total_collected + len(all_fills):,} fills, "
                  f"{elapsed:.0f}s elapsed, "
                  f"~{eta:.0f}s remaining")

    # Final flush
    if all_fills:
        db.upsert_onchain_fills(all_fills)
        total_collected += len(all_fills)

    return total_collected


# --- Verification ---

def verify_collection(db: Database, bot_address: str):
    """Run verification checks on collected on-chain data."""
    print("\n  Verification:")

    onchain_count = db.onchain_fill_count()
    with db._get_conn() as conn:
        trade_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM trades WHERE activity_type='TRADE'"
        ).fetchone()["cnt"]

    print(f"    On-chain fills: {onchain_count:,}")
    print(f"    DB trades:      {trade_count:,}")

    # Coverage: how many trades have on-chain matches
    with db._get_conn() as conn:
        matched = conn.execute("""
            SELECT COUNT(DISTINCT t.transaction_hash) as matched_txs,
                   (SELECT COUNT(DISTINCT transaction_hash)
                    FROM trades WHERE activity_type='TRADE') as total_txs
            FROM trades t
            INNER JOIN onchain_fills o
                ON t.transaction_hash = o.transaction_hash
            WHERE t.activity_type='TRADE'
        """).fetchone()

    matched_txs = matched["matched_txs"]
    total_txs = matched["total_txs"]
    coverage = matched_txs / total_txs * 100 if total_txs > 0 else 0
    print(f"    TX coverage: {matched_txs:,}/{total_txs:,} = {coverage:.1f}%")

    # Maker/taker split
    with db._get_conn() as conn:
        split = conn.execute("""
            SELECT bot_role,
                   COUNT(*) as fills,
                   SUM(CASE WHEN maker_asset_id = '0'
                            THEN maker_amount ELSE taker_amount END) as usdc_vol
            FROM onchain_fills
            GROUP BY bot_role
        """).fetchall()

    for row in split:
        print(f"    {row['bot_role']:6s}: {row['fills']:,} fills, "
              f"${row['usdc_vol']:,.0f} USDC volume")

    # Fee summary
    with db._get_conn() as conn:
        fee_row = conn.execute(
            "SELECT SUM(fee) as total_fee, AVG(fee) as avg_fee "
            "FROM onchain_fills WHERE fee > 0"
        ).fetchone()

    total_fee = fee_row["total_fee"] or 0
    avg_fee = fee_row["avg_fee"] or 0
    print(f"    Total fees: ${total_fee:,.2f}")
    print(f"    Avg fee (non-zero): ${avg_fee:,.4f}")

    # Decode cross-check: compare on-chain USDC amounts to DB usdc_value
    with db._get_conn() as conn:
        check_rows = conn.execute("""
            SELECT
                t.usdc_value,
                o.maker_amount,
                o.taker_amount,
                o.maker_asset_id,
                o.taker_asset_id
            FROM trades t
            INNER JOIN onchain_fills o
                ON t.transaction_hash = o.transaction_hash
                AND (t.asset = o.maker_asset_id OR t.asset = o.taker_asset_id)
            WHERE t.activity_type='TRADE'
            LIMIT 100
        """).fetchall()

    if check_rows:
        mismatches = 0
        checked = 0
        for row in check_rows:
            if row["maker_asset_id"] == "0":
                onchain_usdc = row["maker_amount"]
            elif row["taker_asset_id"] == "0":
                onchain_usdc = row["taker_amount"]
            else:
                continue
            checked += 1
            diff = abs(row["usdc_value"] - onchain_usdc)
            if diff > 0.01:
                mismatches += 1
        print(f"    Decode check ({checked} fills): "
              f"{checked - mismatches} match, {mismatches} mismatches")


# --- Main collection entry point ---

def collect_onchain(db: Database, bot_address: str,
                    skip_receipts: bool = False):
    """Run the full on-chain data collection pipeline.

    Uses batch receipt fetching (public RPCs don't support historical eth_getLogs).
    Samples 50K transactions by default for ~25 min collection time.
    Set POLYGON_ONCHAIN_SAMPLE=0 for full census (~11 hours).
    """
    import os

    print("\n" + "=" * 60)
    print("ON-CHAIN DATA COLLECTION")
    print("=" * 60)

    # Check if already collected
    existing = db.onchain_fill_count()
    if existing > 0:
        print(f"  Already have {existing:,} on-chain fills in DB")
        print("  Skipping collection (delete onchain_fills to re-collect)")
        verify_collection(db, bot_address)
        return

    rpc = PolygonRPC()
    print(f"  RPC: {config.POLYGON_RPC_URL}")
    print(f"  Rate limit: {config.POLYGON_RPC_RATE_LIMIT} req/s")

    # Step 1: Discover topic hash from sample receipt
    order_filled_topic, contract_address = \
        discover_topic_hash(rpc, db, bot_address)

    # Step 2: Collect via batch receipt fetching
    sample_size = int(os.environ.get("POLYGON_ONCHAIN_SAMPLE", "50000"))
    total_fills = collect_via_receipts(
        rpc, db, bot_address,
        order_filled_topic, contract_address,
        sample_size=sample_size)

    total_in_db = db.onchain_fill_count()
    print(f"\n  Total on-chain fills in DB: {total_in_db:,}")

    # Step 3: Verify
    verify_collection(db, bot_address)
