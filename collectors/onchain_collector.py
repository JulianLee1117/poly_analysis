"""On-chain data collector — fetches OrderFilled events from Polygon CTF Exchange.

Three-pass collection:
  Pass 1: OrderFilled where bot is maker (topics[2] = bot_address)
  Pass 2: OrderFilled where bot is taker (topics[3] = bot_address)
  Pass 3: OrdersMatched where bot is taker (topics[2] = bot_address)
         + follow-up receipt fetches for individual fills

Auto-discovers topic hashes and contract address from a sample tx receipt.
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
                    wait = config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** attempt)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if "error" in data:
                    err = data["error"]
                    # Rate limit or server overload — retry
                    if err.get("code", 0) in (-32005, -32000):
                        wait = config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** attempt)
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


# --- Hex decoding helpers ---

def _hex_to_int(h: str) -> int:
    """Convert hex string (with or without 0x) to int."""
    return int(h, 16) if h else 0


def _hex_to_address(h: str) -> str:
    """Convert 32-byte hex topic to 20-byte address (lowercase, checksumless)."""
    # topics are 32 bytes (64 hex chars), address is last 20 bytes (40 hex chars)
    h = h.lower()
    if h.startswith("0x"):
        h = h[2:]
    return "0x" + h[-40:]


def _decode_uint256(hex_chunk: str) -> int:
    """Decode a 64-char hex chunk as uint256."""
    return int(hex_chunk, 16)


def _pad_address(addr: str) -> str:
    """Pad a 20-byte address to 32-byte topic for log filtering."""
    addr = addr.lower()
    if addr.startswith("0x"):
        addr = addr[2:]
    return "0x" + addr.zfill(64)


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

def discover_topic_hashes(rpc: PolygonRPC, db: Database, bot_address: str
                          ) -> Tuple[str, str, str]:
    """Discover OrderFilled topic hash and contract address from a sample tx.

    Returns (order_filled_topic, orders_matched_topic, contract_address).
    orders_matched_topic may be empty if not found.
    """
    # Get a sample transaction hash from our trades DB
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
    orders_matched_topic = None
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
            # OrdersMatched has 3 topics (sig, takerOrderHash, makerAssetId)
            elif len(topics) == 3 and len(data) >= 320:
                orders_matched_topic = topics[0]
                if not contract_address:
                    contract_address = log_addr

    if not order_filled_topic:
        # Try broader search — check all logs for OrderFilled-like shape
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
    if orders_matched_topic:
        print(f"  OrdersMatched topic: {orders_matched_topic[:18]}...")

    return order_filled_topic, orders_matched_topic or "", contract_address


# --- Block range resolution ---

def resolve_block_range(rpc: PolygonRPC, db: Database
                        ) -> Tuple[int, int]:
    """Find the block range covering all trades via binary search.

    Returns (start_block, end_block) with 100-block buffer on each side.
    """
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts "
            "FROM trades WHERE activity_type='TRADE'"
        ).fetchone()

    min_ts = row["min_ts"]
    max_ts = row["max_ts"]
    print(f"  Trade timestamp range: {min_ts} – {max_ts}")

    start_block = _binary_search_block(rpc, min_ts, search_low=True)
    end_block = _binary_search_block(rpc, max_ts, search_low=False)

    # Add buffer
    start_block = max(0, start_block - 100)
    end_block = end_block + 100

    print(f"  Block range: {start_block:,} – {end_block:,} "
          f"({end_block - start_block:,} blocks)")

    return start_block, end_block


def _binary_search_block(rpc: PolygonRPC, target_ts: int,
                         search_low: bool) -> int:
    """Binary search for block number closest to target timestamp.

    If search_low=True, find the first block >= target_ts.
    If search_low=False, find the last block <= target_ts.
    """
    # Get latest block for upper bound
    latest = rpc.call("eth_blockNumber", [])
    hi = _hex_to_int(latest)

    # Estimate starting block: Polygon ~2s/block
    now_ts = int(time.time())
    blocks_ago = (now_ts - target_ts) // 2
    lo = max(0, hi - blocks_ago - 500000)  # generous lower bound

    for _ in range(50):  # max iterations
        if hi - lo <= 1:
            return lo if search_low else hi

        mid = (lo + hi) // 2
        block = rpc.call("eth_getBlockByNumber", [hex(mid), False])

        if not block:
            # Block not found, narrow range
            hi = mid
            continue

        block_ts = _hex_to_int(block.get("timestamp", "0x0"))

        if block_ts < target_ts:
            lo = mid
        elif block_ts > target_ts:
            hi = mid
        else:
            return mid

    return lo if search_low else hi


# --- Collection passes ---

def collect_logs_pass(
    rpc: PolygonRPC,
    start_block: int,
    end_block: int,
    contract_address: str,
    event_topic: str,
    indexed_topic_position: int,  # 1-based topic index for bot address filter
    bot_address: str,
    pass_name: str,
) -> List[dict]:
    """Collect logs for a single pass using eth_getLogs in batches.

    Returns list of raw log dicts.
    """
    batch_size = config.POLYGON_RPC_BATCH_SIZE
    padded_bot = _pad_address(bot_address)
    all_logs = []
    total_batches = (end_block - start_block + batch_size - 1) // batch_size

    print(f"\n  {pass_name}: scanning {total_batches} batches "
          f"({start_block:,} – {end_block:,})...")

    for i, batch_start in enumerate(
            range(start_block, end_block + 1, batch_size)):
        batch_end = min(batch_start + batch_size - 1, end_block)

        # Build topics filter: [event_sig, ...] with bot address at position
        topics = [event_topic]
        while len(topics) < indexed_topic_position:
            topics.append(None)  # null = match any
        topics.append(padded_bot)

        filter_params = {
            "fromBlock": hex(batch_start),
            "toBlock": hex(batch_end),
            "address": contract_address,
            "topics": topics,
        }

        try:
            logs = rpc.call("eth_getLogs", [filter_params])
        except RuntimeError as e:
            if "too many" in str(e).lower() or "10000" in str(e):
                # Batch too large — split in half
                mid = (batch_start + batch_end) // 2
                filter1 = {**filter_params,
                           "toBlock": hex(mid)}
                filter2 = {**filter_params,
                           "fromBlock": hex(mid + 1)}
                logs1 = rpc.call("eth_getLogs", [filter1]) or []
                logs2 = rpc.call("eth_getLogs", [filter2]) or []
                logs = logs1 + logs2
            else:
                raise

        if logs:
            all_logs.extend(logs)

        if (i + 1) % 50 == 0 or i == total_batches - 1:
            print(f"    Batch {i+1}/{total_batches}: "
                  f"{len(all_logs):,} logs so far")

    print(f"  {pass_name} complete: {len(all_logs):,} logs")
    return all_logs


def process_order_filled_logs(
    logs: List[dict],
    bot_address: str,
) -> List[OnchainFill]:
    """Decode OrderFilled logs into OnchainFill objects."""
    fills = []
    for log in logs:
        fill = decode_order_filled(log, bot_address)
        if fill:
            fills.append(fill)
    return fills


def collect_receipt_fills(
    rpc: PolygonRPC,
    tx_hashes: List[str],
    bot_address: str,
    order_filled_topic: str,
) -> List[OnchainFill]:
    """Fetch receipts for tx hashes and extract OrderFilled events.

    Used for Pass 3 follow-up: OrdersMatched transactions where we need
    the individual OrderFilled events from the receipt.
    """
    fills = []
    total = len(tx_hashes)

    for i, tx_hash in enumerate(tx_hashes):
        receipt = rpc.call("eth_getTransactionReceipt", [tx_hash])
        if not receipt:
            continue

        for log in receipt.get("logs", []):
            topics = log.get("topics", [])
            if topics and topics[0] == order_filled_topic:
                fill = decode_order_filled(log, bot_address)
                if fill:
                    fills.append(fill)

        if (i + 1) % 100 == 0:
            print(f"    Receipts: {i+1}/{total}, {len(fills):,} fills")

    return fills


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
                   SUM(maker_amount + taker_amount) as volume
            FROM onchain_fills
            GROUP BY bot_role
        """).fetchall()

    for row in split:
        print(f"    {row['bot_role']:6s}: {row['fills']:,} fills, "
              f"${row['volume']:,.0f} volume")

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

    # Decode cross-check: compare on-chain amounts to DB usdc_value
    with db._get_conn() as conn:
        check_df = conn.execute("""
            SELECT
                t.transaction_hash,
                t.usdc_value,
                o.maker_amount,
                o.taker_amount,
                o.bot_role
            FROM trades t
            INNER JOIN onchain_fills o
                ON t.transaction_hash = o.transaction_hash
                AND (t.asset = o.maker_asset_id OR t.asset = o.taker_asset_id)
            WHERE t.activity_type='TRADE'
            LIMIT 100
        """).fetchall()

    if check_df:
        mismatches = 0
        for row in check_df:
            # The trade usdc_value should approximately match one of the amounts
            onchain_val = (row["taker_amount"] if row["bot_role"] == "maker"
                           else row["maker_amount"])
            diff = abs(row["usdc_value"] - onchain_val)
            if diff > 0.01:
                mismatches += 1
        print(f"    Decode check (100 fills): "
              f"{100 - mismatches} match, {mismatches} mismatches")


# --- Main collection entry point ---

def collect_onchain(db: Database, bot_address: str,
                    skip_receipts: bool = False):
    """Run the full on-chain data collection pipeline.

    1. Discover topic hashes from sample tx
    2. Resolve block range covering all trades
    3. Three-pass log collection
    4. Flush to DB + verify
    """
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

    # Step 1: Discover
    order_filled_topic, orders_matched_topic, contract_address = \
        discover_topic_hashes(rpc, db, bot_address)

    # Step 2: Block range
    start_block, end_block = resolve_block_range(rpc, db)

    # Step 3: Three-pass collection
    all_fills = []
    seen_keys = set()  # (tx_hash, log_index) dedup across passes
    flush_threshold = 5000

    def add_fills(new_fills: List[OnchainFill]):
        nonlocal all_fills
        for f in new_fills:
            key = (f.transaction_hash, f.log_index)
            if key not in seen_keys:
                seen_keys.add(key)
                all_fills.append(f)

        # Flush if buffer is large
        if len(all_fills) >= flush_threshold:
            db.upsert_onchain_fills(all_fills)
            print(f"    Flushed {len(all_fills):,} fills to DB")
            all_fills = []

    # Pass 1: Bot as maker (topics[2] = maker = bot)
    logs1 = collect_logs_pass(
        rpc, start_block, end_block, contract_address,
        order_filled_topic, 2, bot_address,
        "Pass 1 (bot=maker)")
    fills1 = process_order_filled_logs(logs1, bot_address)
    add_fills(fills1)
    print(f"    Decoded {len(fills1):,} fills")

    # Pass 2: Bot as taker (topics[3] = taker = bot)
    logs2 = collect_logs_pass(
        rpc, start_block, end_block, contract_address,
        order_filled_topic, 3, bot_address,
        "Pass 2 (bot=taker)")
    fills2 = process_order_filled_logs(logs2, bot_address)
    add_fills(fills2)
    print(f"    Decoded {len(fills2):,} fills")

    # Pass 3: OrdersMatched (bot as taker via multi-match)
    if orders_matched_topic and not skip_receipts:
        logs3 = collect_logs_pass(
            rpc, start_block, end_block, contract_address,
            orders_matched_topic, 2, bot_address,
            "Pass 3 (OrdersMatched)")

        # Get unique tx hashes from pass 3 not already covered
        covered_txs = {f.transaction_hash for f in fills1 + fills2}
        new_tx_hashes = list({
            log.get("transactionHash", "")
            for log in logs3
        } - covered_txs)

        if new_tx_hashes:
            print(f"    Pass 3 follow-up: {len(new_tx_hashes):,} "
                  f"new tx hashes need receipt fetch")
            fills3 = collect_receipt_fills(
                rpc, new_tx_hashes, bot_address, order_filled_topic)
            add_fills(fills3)
            print(f"    Decoded {len(fills3):,} fills from receipts")
        else:
            print("    Pass 3: no new tx hashes beyond passes 1-2")
    elif skip_receipts:
        print("\n  Pass 3 skipped (--no-receipts)")
    else:
        print("\n  Pass 3 skipped (no OrdersMatched topic found)")

    # Final flush
    if all_fills:
        db.upsert_onchain_fills(all_fills)
        print(f"    Final flush: {len(all_fills):,} fills")

    total = db.onchain_fill_count()
    print(f"\n  Total on-chain fills in DB: {total:,}")
    print(f"  Dedup keys tracked: {len(seen_keys):,}")

    # Step 4: Verify
    verify_collection(db, bot_address)
