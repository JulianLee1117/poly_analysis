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

    def per_market_summary(self) -> pd.DataFrame:
        """Per-condition_id trade aggregates via SQL. One row per market.

        Returns ~8,313 rows with buy/sell costs, shares, fill counts per outcome.
        Foundation for all Phase 3+ analysis. Never loads raw trades.
        """
        query = """
        SELECT
            condition_id,
            SUM(CASE WHEN side='BUY' AND outcome='Up' THEN usdc_value ELSE 0 END) as buy_up_cost,
            SUM(CASE WHEN side='BUY' AND outcome='Up' THEN size ELSE 0 END) as buy_up_shares,
            SUM(CASE WHEN side='BUY' AND outcome='Down' THEN usdc_value ELSE 0 END) as buy_down_cost,
            SUM(CASE WHEN side='BUY' AND outcome='Down' THEN size ELSE 0 END) as buy_down_shares,
            SUM(CASE WHEN side='SELL' AND outcome='Up' THEN usdc_value ELSE 0 END) as sell_up_proceeds,
            SUM(CASE WHEN side='SELL' AND outcome='Up' THEN size ELSE 0 END) as sell_up_shares,
            SUM(CASE WHEN side='SELL' AND outcome='Down' THEN usdc_value ELSE 0 END) as sell_down_proceeds,
            SUM(CASE WHEN side='SELL' AND outcome='Down' THEN size ELSE 0 END) as sell_down_shares,
            COUNT(*) as total_fills,
            SUM(CASE WHEN side='BUY' THEN 1 ELSE 0 END) as buy_fills,
            SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) as sell_fills,
            MIN(timestamp) as first_fill_ts,
            MAX(timestamp) as last_fill_ts
        FROM trades WHERE activity_type = 'TRADE'
        GROUP BY condition_id
        """
        with self._get_conn() as conn:
            return pd.read_sql_query(query, conn)

    def per_market_execution_detail(self) -> pd.DataFrame:
        """Per-market execution timestamps by outcome. One row per market.

        Adds per-outcome first/last buy timestamps, first sell timestamp,
        and per-outcome buy fill counts for sequencing and entry speed analysis.
        """
        query = """
        SELECT
            condition_id,
            MIN(CASE WHEN side='BUY' AND outcome='Up' THEN timestamp END) as first_buy_up_ts,
            MAX(CASE WHEN side='BUY' AND outcome='Up' THEN timestamp END) as last_buy_up_ts,
            MIN(CASE WHEN side='BUY' AND outcome='Down' THEN timestamp END) as first_buy_down_ts,
            MAX(CASE WHEN side='BUY' AND outcome='Down' THEN timestamp END) as last_buy_down_ts,
            MIN(CASE WHEN side='SELL' THEN timestamp END) as first_sell_ts,
            MAX(CASE WHEN side='SELL' THEN timestamp END) as last_sell_ts,
            SUM(CASE WHEN side='BUY' AND outcome='Up' THEN 1 ELSE 0 END) as buy_up_fills,
            SUM(CASE WHEN side='BUY' AND outcome='Down' THEN 1 ELSE 0 END) as buy_down_fills,
            SUM(CASE WHEN side='SELL' AND outcome='Up' THEN 1 ELSE 0 END) as sell_up_fills,
            SUM(CASE WHEN side='SELL' AND outcome='Down' THEN 1 ELSE 0 END) as sell_down_fills
        FROM trades WHERE activity_type = 'TRADE'
        GROUP BY condition_id
        """
        with self._get_conn() as conn:
            return pd.read_sql_query(query, conn)

    def price_trajectory_summary(self) -> pd.DataFrame:
        """Per-market per-outcome price trajectory: first-5 vs last-5 avg buy price.

        Uses window functions. Returns ~16K rows (2 outcomes × ~8K markets).
        """
        query = """
        WITH ranked AS (
            SELECT
                condition_id, outcome, price,
                ROW_NUMBER() OVER (
                    PARTITION BY condition_id, outcome
                    ORDER BY timestamp, rowid
                ) as rn_asc,
                ROW_NUMBER() OVER (
                    PARTITION BY condition_id, outcome
                    ORDER BY timestamp DESC, rowid DESC
                ) as rn_desc
            FROM trades
            WHERE activity_type = 'TRADE' AND side = 'BUY'
        )
        SELECT
            condition_id,
            outcome,
            AVG(CASE WHEN rn_asc <= 5 THEN price END) as first_5_avg,
            AVG(CASE WHEN rn_desc <= 5 THEN price END) as last_5_avg,
            MIN(price) as min_price,
            MAX(price) as max_price,
            COUNT(*) as buy_fills
        FROM ranked
        GROUP BY condition_id, outcome
        """
        with self._get_conn() as conn:
            return pd.read_sql_query(query, conn)

    def position_pnl_by_condition(self) -> pd.DataFrame:
        """Per-condition_id P&L from positions table (ground truth).

        Sums realized_pnl across outcomes (Up/Down) per condition_id.
        Uses close_timestamp for P&L timing (when market resolved).
        """
        query = """
        SELECT
            condition_id,
            SUM(realized_pnl) as position_pnl,
            MAX(close_timestamp) as close_ts,
            COUNT(*) as position_count,
            SUM(total_bought) as total_bought
        FROM positions
        WHERE is_closed = 1
        GROUP BY condition_id
        """
        with self._get_conn() as conn:
            return pd.read_sql_query(query, conn)

    def market_fills(self, condition_id: str) -> pd.DataFrame:
        """All fills for a single market, ordered by timestamp."""
        with self._get_conn() as conn:
            return pd.read_sql_query(
                """SELECT timestamp, side, outcome, price, size, usdc_value
                   FROM trades
                   WHERE condition_id = ? AND activity_type = 'TRADE'
                   ORDER BY timestamp""",
                conn,
                params=(condition_id,),
            )

    def daily_summary(self) -> pd.DataFrame:
        """Daily trade count, volume, and market count."""
        query = """
        SELECT
            date(timestamp, 'unixepoch') as trade_date,
            COUNT(*) as fills,
            SUM(usdc_value) as volume,
            COUNT(DISTINCT condition_id) as markets,
            SUM(CASE WHEN side='BUY' THEN usdc_value ELSE 0 END) as buy_volume,
            SUM(CASE WHEN side='SELL' THEN usdc_value ELSE 0 END) as sell_volume
        FROM trades WHERE activity_type = 'TRADE'
        GROUP BY date(timestamp, 'unixepoch')
        ORDER BY trade_date
        """
        with self._get_conn() as conn:
            return pd.read_sql_query(query, conn)
