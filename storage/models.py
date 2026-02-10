"""Data models for Polymarket analysis."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Trade:
    transaction_hash: str
    asset: str  # token ID
    side: str  # BUY or SELL
    outcome: str  # YES or NO
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


@dataclass
class Position:
    asset: str  # token ID
    condition_id: str
    outcome: str  # YES or NO
    size: float  # current shares held
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    current_value: float = 0.0
    is_closed: bool = False
    market_question: str = ""
