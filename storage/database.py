"""SQLite database for storing collected Polymarket data."""

import json
import sqlite3
from typing import List, Optional

import pandas as pd

import config
from storage.models import Trade, Market, Position

# Schema definitions
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    transaction_hash TEXT NOT NULL,
    asset TEXT NOT NULL,
    side TEXT NOT NULL,
    outcome TEXT NOT NULL,
    size REAL NOT NULL,
    price REAL NOT NULL,
    usdc_value REAL NOT NULL,
    timestamp INTEGER NOT NULL,
    condition_id TEXT NOT NULL,
    fee REAL DEFAULT 0.0,
    maker_address TEXT,
    activity_type TEXT DEFAULT 'TRADE',
    PRIMARY KEY (transaction_hash, asset)
);

CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_condition_id ON trades(condition_id);
CREATE INDEX IF NOT EXISTS idx_trades_activity_type ON trades(activity_type);

CREATE TABLE IF NOT EXISTS markets (
    condition_id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    slug TEXT DEFAULT '',
    category TEXT DEFAULT '',
    end_date TEXT,
    created_at TEXT,
    active INTEGER DEFAULT 1,
    closed INTEGER DEFAULT 0,
    volume REAL DEFAULT 0.0,
    liquidity REAL DEFAULT 0.0,
    spread REAL DEFAULT 0.0,
    outcome_prices TEXT DEFAULT '',
    description TEXT DEFAULT '',
    tokens TEXT DEFAULT '',
    neg_risk INTEGER DEFAULT 0,
    neg_risk_market_id TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS positions (
    asset TEXT PRIMARY KEY,
    condition_id TEXT NOT NULL,
    outcome TEXT NOT NULL,
    size REAL NOT NULL,
    avg_price REAL DEFAULT 0.0,
    total_bought REAL DEFAULT 0.0,
    realized_pnl REAL DEFAULT 0.0,
    cur_price REAL DEFAULT 0.0,
    current_value REAL DEFAULT 0.0,
    initial_value REAL DEFAULT 0.0,
    cash_pnl REAL DEFAULT 0.0,
    is_closed INTEGER DEFAULT 0,
    opposite_outcome TEXT DEFAULT '',
    opposite_asset TEXT DEFAULT '',
    end_date TEXT DEFAULT '',
    close_timestamp INTEGER DEFAULT 0,
    market_slug TEXT DEFAULT '',
    market_question TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_positions_condition_id ON positions(condition_id);

CREATE TABLE IF NOT EXISTS collection_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, db_path: Optional[str] = None):
        import os
        self.db_path = db_path or config.DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._get_conn() as conn:
            conn.executescript(SCHEMA_SQL)

    # --- Upsert methods ---

    def upsert_trades(self, trades: List[Trade]):
        if not trades:
            return
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO trades
                   (transaction_hash, asset, side, outcome, size, price,
                    usdc_value, timestamp, condition_id, fee, maker_address, activity_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (t.transaction_hash, t.asset, t.side, t.outcome, t.size,
                     t.price, t.usdc_value, t.timestamp, t.condition_id,
                     t.fee, t.maker_address, t.activity_type)
                    for t in trades
                ],
            )

    def upsert_markets(self, markets: List[Market]):
        if not markets:
            return
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO markets
                   (condition_id, question, slug, category, end_date, created_at,
                    active, closed, volume, liquidity, spread, outcome_prices,
                    description, tokens, neg_risk, neg_risk_market_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (m.condition_id, m.question, m.slug, m.category, m.end_date,
                     m.created_at, int(m.active), int(m.closed), m.volume,
                     m.liquidity, m.spread, m.outcome_prices, m.description,
                     m.tokens, int(m.neg_risk), m.neg_risk_market_id)
                    for m in markets
                ],
            )

    def upsert_positions(self, positions: List[Position]):
        if not positions:
            return
        with self._get_conn() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO positions
                   (asset, condition_id, outcome, size, avg_price, total_bought,
                    realized_pnl, cur_price, current_value, initial_value, cash_pnl,
                    is_closed, opposite_outcome, opposite_asset, end_date,
                    close_timestamp, market_slug, market_question)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (p.asset, p.condition_id, p.outcome, p.size, p.avg_price,
                     p.total_bought, p.realized_pnl, p.cur_price, p.current_value,
                     p.initial_value, p.cash_pnl, int(p.is_closed),
                     p.opposite_outcome, p.opposite_asset, p.end_date,
                     p.close_timestamp, p.market_slug, p.market_question)
                    for p in positions
                ],
            )

    def set_metadata(self, key: str, value: str):
        import time
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO collection_metadata (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, value, int(time.time())),
            )

    def get_metadata(self, key: str) -> Optional[str]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM collection_metadata WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    # --- DataFrame loaders ---

    def load_trades(self, activity_type: str = "TRADE") -> pd.DataFrame:
        with self._get_conn() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM trades WHERE activity_type = ? ORDER BY timestamp",
                conn,
                params=(activity_type,),
            )
        if not df.empty:
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        return df

    def load_all_trades(self) -> pd.DataFrame:
        with self._get_conn() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM trades ORDER BY timestamp", conn
            )
        if not df.empty:
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        return df

    def load_markets(self) -> pd.DataFrame:
        with self._get_conn() as conn:
            return pd.read_sql_query("SELECT * FROM markets", conn)

    def load_positions(self, closed_only: bool = False) -> pd.DataFrame:
        query = "SELECT * FROM positions"
        if closed_only:
            query += " WHERE is_closed = 1"
        with self._get_conn() as conn:
            return pd.read_sql_query(query, conn)

    # --- Stats ---

    def trade_count(self, activity_type: str = "TRADE") -> int:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM trades WHERE activity_type = ?",
                (activity_type,),
            ).fetchone()
            return row["cnt"]

    def market_count(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM markets").fetchone()
            return row["cnt"]

    def position_count(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM positions").fetchone()
            return row["cnt"]

    def trade_summary_stats(self) -> dict:
        """Return summary stats for trades using SQL aggregation."""
        with self._get_conn() as conn:
            row = conn.execute("""
                SELECT
                    SUM(usdc_value) as total_volume,
                    date(MIN(timestamp), 'unixepoch') as min_date,
                    date(MAX(timestamp), 'unixepoch') as max_date,
                    CAST(julianday(date(MAX(timestamp), 'unixepoch'))
                         - julianday(date(MIN(timestamp), 'unixepoch')) + 1 AS INTEGER) as days_active
                FROM trades WHERE activity_type = 'TRADE'
            """).fetchone()
            return {
                "total_volume": row["total_volume"] or 0,
                "min_date": row["min_date"] or "",
                "max_date": row["max_date"] or "",
                "days_active": row["days_active"] or 0,
            }

    def get_asset_per_condition_id(self) -> dict:
        """Return {condition_id: asset} mapping using one asset per condition_id.

        Uses SQL aggregation to avoid loading 1.3M rows into memory.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT condition_id, MIN(asset) as asset FROM trades GROUP BY condition_id"
            ).fetchall()
            return {row["condition_id"]: row["asset"] for row in rows}
