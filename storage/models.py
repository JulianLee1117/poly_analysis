"""Data models for Polymarket analysis."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Trade:
    transaction_hash: str
    asset: str  # token ID
    side: str  # BUY or SELL
    outcome: str  # Up or Down
    size: float  # number of shares
    price: float  # price per share in USDC
    usdc_value: float  # total USDC value (size * price)
    timestamp: int  # unix epoch seconds
    condition_id: str  # links to market
    fee: float = 0.0
    maker_address: Optional[str] = None
    activity_type: str = "TRADE"  # TRADE or MAKER_REBATE


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str = ""
    category: str = ""
    end_date: Optional[str] = None
    created_at: Optional[str] = None
    active: bool = True
    closed: bool = False
    volume: float = 0.0
    liquidity: float = 0.0
    spread: float = 0.0
    outcome_prices: str = ""  # JSON string of current prices
    description: str = ""
    tokens: str = ""  # JSON string of token info
    neg_risk: bool = False
    neg_risk_market_id: str = ""


@dataclass
class Position:
    asset: str  # token ID
    condition_id: str
    outcome: str  # Up or Down
    size: float  # current shares held (0 for closed)
    avg_price: float = 0.0
    total_bought: float = 0.0  # total USDC spent buying
    realized_pnl: float = 0.0
    cur_price: float = 0.0  # resolution price: 1=won, 0=lost
    current_value: float = 0.0
    initial_value: float = 0.0
    cash_pnl: float = 0.0
    is_closed: bool = False
    opposite_outcome: str = ""  # the other side (Up↔Down)
    opposite_asset: str = ""  # token ID of the other side
    end_date: str = ""  # market end date
    close_timestamp: int = 0  # when position was closed
    market_slug: str = ""
    market_question: str = ""
