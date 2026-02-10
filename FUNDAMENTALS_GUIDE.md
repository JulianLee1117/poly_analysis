# Polymarket Bot Fundamentals Guide

> Everything you need to understand to build and operate an automated trading bot on Polymarket — from crypto primitives to quant strategy.

---

## Table of Contents

1. [Prediction Markets 101](#1-prediction-markets-101)
2. [Crypto / Blockchain Layer](#2-crypto--blockchain-layer)
3. [Polymarket Platform Architecture](#3-polymarket-platform-architecture)
4. [Trading Fundamentals](#4-trading-fundamentals)
5. [Quantitative Concepts](#5-quantitative-concepts)
6. [Bot Strategy Archetypes](#6-bot-strategy-archetypes)
7. [Polymarket API & Technical Stack](#7-polymarket-api--technical-stack)
8. [Risk Management](#8-risk-management)
9. [Analyzing Another Trader's Bot](#9-analyzing-another-traders-bot)
10. [Learning Path & Resources](#10-learning-path--resources)

---

## 1. Prediction Markets 101

### What is a prediction market?

A prediction market lets you trade contracts on the outcome of real-world events. Each contract resolves to either **$1** (event happened) or **$0** (event didn't happen). The current price of a contract is the market's **implied probability** of that outcome.

| Concept | Explanation |
|---------|------------|
| **Binary outcome** | Every market has a YES and a NO side. If you buy YES at $0.60, you're saying "I think there's >60% chance this happens." |
| **Price = Probability** | A YES price of $0.73 means the market collectively estimates a 73% chance the event occurs. |
| **Sum-to-one constraint** | In theory, `price(YES) + price(NO) = $1.00`. When this doesn't hold, there's an arbitrage opportunity. |
| **Resolution** | When the event's outcome is determined, contracts settle: YES holders get $1 if the event happened, $0 otherwise. NO holders get the inverse. |
| **Payout** | If you buy YES at $0.40 and the event occurs, you profit $0.60 per contract. If it doesn't, you lose $0.40. |

### Why prediction markets matter for quant trading

- Markets are **informationally efficient** — prices aggregate dispersed knowledge
- But they're **not perfectly efficient** — there are persistent mispricings, especially around:
  - News events (slow information incorporation)
  - Low-liquidity markets (wide spreads, stale prices)
  - Multi-outcome markets (complex probability distributions)
  - Behavioral biases (favorite-longshot bias, round-number anchoring)

### Key difference from sports betting

Prediction markets have a **continuous order book** — you can enter and exit positions at any time before resolution, not just place a bet and wait. This is what makes automated market making and arbitrage possible.

---

## 2. Crypto / Blockchain Layer

You don't need to be a blockchain expert, but you need to understand the plumbing.

### Core concepts

| Concept | What you need to know |
|---------|----------------------|
| **Ethereum** | The base blockchain. Polymarket's smart contracts are Ethereum-compatible. Your wallet and keys are Ethereum-format. |
| **Polygon (PoS)** | A Layer 2 scaling network on top of Ethereum. Polymarket runs here because it's fast and cheap (fractions of a cent per tx vs $5+ on Ethereum mainnet). |
| **USDC** | A stablecoin pegged 1:1 to USD. This is your trading currency on Polymarket. You deposit USDC, trade with USDC, and withdraw USDC. |
| **Wallet** | A public/private key pair. Your **public address** (0x...) is your identity. Your **private key** signs transactions and must never be shared. |
| **MetaMask** | A browser-based wallet. You'll use it (or a programmatic equivalent) to sign orders. |
| **Gas fees** | Transaction costs on Polygon. Very cheap (~$0.001-0.01) but they exist. Your bot needs a small amount of MATIC (Polygon's native token) for gas. |
| **ERC-20** | Token standard. USDC is an ERC-20 token. |
| **ERC-1155** | Multi-token standard. Polymarket's outcome tokens (YES/NO shares) are ERC-1155 tokens — this is important for on-chain settlement. |

### Bridging funds

To get USDC onto Polygon:
1. Buy USDC on a CEX (Coinbase, Binance, etc.)
2. Withdraw directly to Polygon address, OR
3. Bridge from Ethereum mainnet to Polygon via the Polygon Bridge
4. Polymarket also supports direct deposit via credit card / bank in some jurisdictions

### Wallets for bots

For automated trading, you'll use a **programmatic wallet** (not MetaMask):
- Generate a private key and derive the address
- Store the private key securely (env var, secrets manager — never in code)
- Use `eth_account` or `web3.py` to sign transactions programmatically
- The private key signs your CLOB API requests (HMAC-SHA256 auth)

### Conditional Token Framework (CTF)

Polymarket uses Gnosis's **Conditional Token Framework** under the hood:
- Each market has a **condition** (the question being asked)
- Each condition has **outcome slots** (YES / NO, or multiple outcomes)
- When you buy YES shares, you're minting conditional tokens
- On resolution, winning tokens are redeemable for USDC at $1 each
- This all happens on-chain — the smart contracts guarantee settlement

---

## 3. Polymarket Platform Architecture

### Hybrid design: off-chain matching, on-chain settlement

```
┌─────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  Your Bot    │────▶│  CLOB (off-chain) │────▶│ Polygon (on-chain) │
│  (API calls) │◀────│  Order matching   │◀────│ Token settlement   │
└─────────────┘     └──────────────────┘     └───────────────────┘
```

- **Off-chain order book** — Orders are submitted to Polymarket's Central Limit Order Book (CLOB). Matching happens off-chain for speed (~500ms execution).
- **On-chain settlement** — Matched trades settle on Polygon. Tokens transfer between wallets on-chain. This gives you verifiable, trustless settlement.
- **Hybrid benefit** — You get CEX-like speed with DEX-like transparency and custody.

### Key components

| Component | Role |
|-----------|------|
| **CLOB** | Central Limit Order Book — the matching engine. Accepts limit orders, matches them, reports fills. |
| **REST API** | Request/response API for placing orders, fetching markets, getting balances, querying trade history. |
| **WebSocket API** | Real-time streaming for order book updates, price ticks, user fills/order status changes. |
| **Gamma Markets API** | Metadata layer — market descriptions, categories, resolution sources, open/close times. |
| **CTF Exchange** | On-chain smart contract that handles token minting, trading, and redemption. |

### Authentication

Polymarket uses **API key + HMAC-SHA256 signature** auth:

1. Generate API credentials (key, secret, passphrase) through the Polymarket UI or programmatically
2. Each request includes headers:
   - `POLY_API_KEY` — your public key
   - `POLY_SIGNATURE` — HMAC-SHA256 of the request body using your secret
   - `POLY_TIMESTAMP` — Unix timestamp (requests expire after 30 seconds)
   - `POLY_PASSPHRASE` — additional auth token
3. Orders are also signed with your Ethereum private key (proving wallet ownership)

### Rate limits

- REST API: typically 100-200 requests/second (check current docs)
- WebSocket: connection limits per API key
- Order submission: rate limits per market and globally
- Exceeding limits returns 429 errors — your bot needs backoff logic

---

## 4. Trading Fundamentals

### Order types

| Type | Behavior | When to use |
|------|----------|-------------|
| **Limit order** | Sits in the book at your specified price until filled or cancelled | Market making, precise entries/exits |
| **Market order** | Fills immediately against resting orders at best available price | Urgent execution, arbitrage capture |
| **GTC (Good-Til-Cancelled)** | Limit order that persists until you cancel it | Default for most strategies |
| **FOK (Fill-Or-Kill)** | Must fill entirely and immediately, or cancel entirely | When partial fills are unacceptable |
| **GTD (Good-Til-Date)** | Limit order that expires at a specified time | Time-sensitive strategies |

### The order book

```
        ASKS (people selling YES / buying NO)
        ─────────────────────────────────
Price   │  $0.65  │  200 contracts       │  ← best ask
        │  $0.66  │  500 contracts       │
        │  $0.67  │  150 contracts       │
        ─────────────────────────────────
        │  $0.63  │  300 contracts       │  ← best bid
        │  $0.62  │  450 contracts       │
        │  $0.61  │  100 contracts       │
        ─────────────────────────────────
        BIDS (people buying YES / selling NO)

Spread = best ask - best bid = $0.65 - $0.63 = $0.02
Mid price = (best ask + best bid) / 2 = $0.64
```

Key order book concepts:
- **Bid-ask spread** — The gap between the highest bid and lowest ask. Wider spread = less liquidity = more profit opportunity for market makers.
- **Depth** — How many contracts are available at each price level. Thin depth means your order will move the price (slippage).
- **Mid price** — The fair-value estimate: average of best bid and best ask.
- **Maker vs Taker** — Maker adds liquidity (limit order that rests in the book). Taker removes liquidity (market order or crossing limit order). Makers often get fee rebates.

### Fees on Polymarket

- **Taker fee**: ~2% (you pay this when your order crosses the spread and fills immediately)
- **Maker rebate**: sometimes ~0% or slightly positive (you earn a small rebate for providing resting liquidity)
- **Important**: Your bot's strategy must be profitable **after fees**. A 1-cent edge on a 2-cent fee market is not an edge.
- Check the current fee schedule — it changes. Some markets and the Builder Program offer different rates.

### Position P&L

```
P&L = (Exit Price - Entry Price) × Quantity  [for YES positions]
P&L = (Entry Price - Exit Price) × Quantity  [for NO positions]

If held to resolution:
  P&L (YES) = ($1.00 - Entry Price) × Quantity  [if event occurs]
  P&L (YES) = ($0.00 - Entry Price) × Quantity  [if event doesn't occur, i.e., you lose your cost basis]
```

### Liquidity

Liquidity matters enormously for bots:
- **High liquidity** markets (elections, major events): tight spreads ($0.01-0.02), deep books, hard to find edge, many competing bots
- **Low liquidity** markets (niche events): wide spreads ($0.05-0.15+), thin books, easier edge but harder to size up, slippage risk
- Your strategy choice depends on which liquidity regime you target

---

## 5. Quantitative Concepts

### 5.1 Expected Value (EV)

The single most important concept. Every trade should have positive expected value.

```
EV = P(win) × Profit_if_win  -  P(lose) × Loss_if_lose

Example:
  You buy YES at $0.40
  You estimate true probability = 55%
  
  EV = 0.55 × $0.60  -  0.45 × $0.40
     = $0.33 - $0.18
     = +$0.15 per contract
```

Your **edge** is the difference between your estimated true probability and the market's implied probability:
```
Edge = Your_estimated_P - Market_implied_P
     = 0.55 - 0.40
     = 0.15 (15 percentage points)
```

If your edge is consistently positive over many trades, you make money. The hard part is **actually having a better probability estimate than the market**.

### 5.2 Kelly Criterion

How much of your bankroll to bet on a given edge. Overbetting destroys bankrolls even with positive EV.

```
Kelly fraction = edge / odds

For binary markets:
  f* = (p × b - q) / b

Where:
  p = your estimated probability of winning
  q = 1 - p (probability of losing)
  b = payout odds (profit / risk)

Example:
  Buy YES at $0.40 → b = $0.60 / $0.40 = 1.5
  Your estimate: p = 0.55, q = 0.45
  
  f* = (0.55 × 1.5 - 0.45) / 1.5
     = (0.825 - 0.45) / 1.5
     = 0.25

Kelly says bet 25% of bankroll. In practice, use FRACTIONAL Kelly (e.g., half-Kelly = 12.5%) because:
  - Your probability estimates are uncertain
  - Kelly assumes infinite time horizon
  - Drawdowns on full Kelly are psychologically brutal (~50% drawdowns are normal)
```

**Half-Kelly or quarter-Kelly** is standard for real trading.

### 5.3 Implied Probability & Calibration

```
Implied probability = Market price (for YES)
                    = 1 - Market price (for NO)
```

Your job is to determine if the implied probability is **wrong**. Sources of edge:
- **Fundamental analysis** — You know something the market hasn't priced in (news, data, domain expertise)
- **Model-based** — You have a statistical model that predicts probabilities better than the crowd
- **Structural** — The market has systematic biases you can exploit (e.g., favorite-longshot bias)
- **Speed** — You react to new information faster than the market adjusts

### 5.4 Market Making Math

If you're building a market-making bot, you need to understand:

**Spread capture:**
```
Gross profit per round trip = ask_price - bid_price
Net profit = spread - fees - adverse_selection_cost

Example:
  You quote: Bid $0.62, Ask $0.66 (spread = $0.04)
  Fees: ~$0.01 per side = $0.02 total
  If someone buys your ask and you buy back at bid:
    Net = $0.04 - $0.02 = $0.02 per round trip
  
  BUT if the price moves against you (adverse selection):
    Price jumps to $0.70 after you sell at $0.66
    You lose $0.04 on that trade
```

**Inventory risk:**
- As you accumulate a directional position (e.g., too many YES shares), you're exposed to price risk
- Market makers **skew quotes** to reduce inventory:
  - Too much YES inventory → lower your bid, lower your ask (encourage selling to you less, buying from you more)
  - Too much NO inventory → raise your bid, raise your ask

**The Avellaneda-Stoikov model** is the classic framework:
```
Reservation price = mid_price - inventory × risk_aversion × volatility² × time_remaining
Optimal spread = risk_aversion × volatility² × time_remaining + (2/risk_aversion) × ln(1 + risk_aversion/k)
```
You don't need to implement this exactly, but understand the principles: spread widens with volatility, quotes skew with inventory.

### 5.5 Arbitrage Math

**Sum-to-one arbitrage:**
```
If YES_price + NO_price > $1.00:
  Sell YES and Sell NO → guaranteed profit
  Profit = (YES_price + NO_price) - $1.00 - fees

If YES_price + NO_price < $1.00:
  Buy YES and Buy NO → guaranteed profit
  Profit = $1.00 - (YES_price + NO_price) - fees
```

**Cross-market arbitrage:**
```
Market A: "Will X happen by March?"  YES = $0.70
Market B: "Will X happen by June?"   YES = $0.65

This is mispriced — if X happens by March, it also happens by June.
  Buy YES on B ($0.65), Sell YES on A ($0.70)
  Risk-free $0.05 if A resolves YES (both resolve YES)
  
But there's a timing risk if A resolves NO and B resolves YES later.
```

**Multi-outcome arbitrage:**
```
Market: "Who will win the election?" with candidates A, B, C

If P(A) + P(B) + P(C) > 1.00 → sell all outcomes
If P(A) + P(B) + P(C) < 1.00 → buy all outcomes
```

### 5.6 Volatility & Time Decay

Prediction market contracts have option-like properties:
- **As resolution date approaches**, prices tend toward 0 or 1 (uncertainty resolves)
- **Volatility** = how much prices move. High-volatility markets need wider spreads.
- **Time value** — A contract at $0.50 with 6 months to resolution has more uncertainty (and opportunity) than the same at $0.50 with 1 day to go

Estimating volatility:
```
Historical volatility = std_dev(price_returns) over a lookback window
Realized vol = annualized standard deviation of log returns

For prediction markets, a simpler heuristic often works:
  vol ≈ sqrt(p × (1-p))  where p is the current price
  (This is the variance of a Bernoulli random variable)
```

### 5.7 Bayesian Updating

How to update your probability estimates as new information arrives:

```
P(event | new_data) = P(new_data | event) × P(event) / P(new_data)

Posterior = Likelihood × Prior / Evidence
```

Example: A market is at $0.50 (50% chance). A new poll comes out. Your model says this poll result would happen 70% of the time if the event occurs, and 30% of the time if it doesn't.

```
P(event | poll) = (0.70 × 0.50) / (0.70 × 0.50 + 0.30 × 0.50)
               = 0.35 / 0.50
               = 0.70

New estimate: 70%. Market is at 50%. You have a 20-point edge → BUY.
```

### 5.8 Sharpe Ratio & Performance Metrics

```
Sharpe Ratio = (Mean Return - Risk-Free Rate) / Std Dev of Returns

For prediction market bots:
  - Track daily/weekly P&L
  - Aim for Sharpe > 2 (good), > 3 (excellent)
  
Other metrics:
  - Win rate: % of trades that are profitable
  - Profit factor: gross_profit / gross_loss (want > 1.5)
  - Max drawdown: largest peak-to-trough decline
  - Calmar ratio: annualized return / max drawdown
```

---

## 6. Bot Strategy Archetypes

### 6.1 Market Making Bot

**What it does:** Continuously places bid and ask orders on both sides of a market, earning the spread.

**Key components:**
- Fair price estimator (mid price, model-based, or Bayesian)
- Spread calculator (wider in volatile/illiquid markets)
- Inventory manager (skew quotes to flatten position)
- Quote updater (cancel and replace stale orders on price moves)

**Pseudocode:**
```python
while True:
    mid = get_mid_price(market)
    vol = estimate_volatility(market)
    inv = get_inventory()
    
    # Skew based on inventory
    skew = -inv * RISK_AVERSION * vol
    
    # Calculate quotes
    half_spread = BASE_SPREAD + vol * SPREAD_FACTOR
    bid = mid + skew - half_spread
    ask = mid + skew + half_spread
    
    # Size based on Kelly + inventory limits
    size = min(KELLY_SIZE, MAX_INVENTORY - abs(inv))
    
    cancel_stale_orders()
    place_limit_order(BUY, bid, size)
    place_limit_order(SELL, ask, size)
    
    sleep(QUOTE_INTERVAL)
```

**Risks:**
- Adverse selection (informed traders pick you off)
- Inventory blowup (one-sided flow leaves you directionally exposed)
- Stale quotes during fast moves (you get picked off at bad prices)

### 6.2 Arbitrage Bot

**What it does:** Detects mispricings and executes risk-free (or near-risk-free) trades.

**Types:**
1. **Sum-to-one**: Monitor YES + NO prices. When they deviate from $1.00 by more than fees, execute.
2. **Cross-market**: Find related markets where prices are inconsistent.
3. **Multi-outcome**: In markets with 3+ outcomes, verify that probabilities sum to ~1.

**Pseudocode:**
```python
while True:
    for market in all_markets:
        yes_price = get_best_ask("YES", market)
        no_price = get_best_ask("NO", market)
        
        cost_to_buy_both = yes_price + no_price
        
        if cost_to_buy_both < 1.00 - TOTAL_FEES:
            buy("YES", yes_price, SIZE)
            buy("NO", no_price, SIZE)
            # Guaranteed profit = 1.00 - cost - fees
        
        yes_bid = get_best_bid("YES", market)
        no_bid = get_best_bid("NO", market)
        
        revenue_from_selling_both = yes_bid + no_bid
        
        if revenue_from_selling_both > 1.00 + TOTAL_FEES:
            sell("YES", yes_bid, SIZE)
            sell("NO", no_bid, SIZE)
    
    sleep(SCAN_INTERVAL)
```

**Risks:**
- Execution risk (one leg fills, other doesn't)
- Fee miscalculation
- Race conditions with other arb bots
- Markets that look related but have different resolution criteria

### 6.3 News/Signal-Based Bot

**What it does:** Reacts to external information faster than the market.

**Sources:**
- News APIs (AP, Reuters, Twitter/X firehose)
- Data feeds (economic indicators, election results, weather data)
- LLM-based analysis of unstructured text
- Social sentiment aggregation

**Key challenge:** Speed. If you can parse a news headline and determine its impact on a market 2 seconds before other traders, that's your edge. If you're 2 seconds late, you're the one getting picked off.

### 6.4 Model-Based / Statistical Bot

**What it does:** Uses a statistical model to estimate true probabilities, then trades against mispricings.

**Examples:**
- Election model (like 538/Silver Bulletin) that outputs probabilities → compare to Polymarket prices
- Weather model for weather-related markets
- Sports model using ELO/historical data
- LLM-based reasoning for geopolitical events

**Key insight:** Your model doesn't need to be right every time — it just needs to be **better calibrated** than the market on average.

### 6.5 Copy Trading Bot

**What it does:** Monitors a profitable trader's wallet and mirrors their trades.

**How to implement:**
1. Watch the target wallet's on-chain transactions or Polymarket API activity
2. When they enter a position, enter the same position (with appropriate sizing)
3. When they exit, exit

**Risks:**
- Latency: by the time you copy, the price may have moved
- Strategy mismatch: they may have a hedged portfolio you can't see
- Detection: they may front-run their own public activity
- Size impact: your copy trade moves the price, worsening your entry

---

## 7. Polymarket API & Technical Stack

### 7.1 APIs you need

| API | Base URL | Purpose |
|-----|----------|---------|
| **CLOB REST** | `https://clob.polymarket.com` | Place/cancel orders, get order book, trade history |
| **CLOB WebSocket** | `wss://ws-subscriptions-clob.polymarket.com/ws/...` | Real-time order book, trades, user events |
| **Gamma REST** | `https://gamma-api.polymarket.com` | Market metadata, descriptions, resolution info |
| **Strapi/CMS** | `https://strapi-matic.polymarket.com` | Additional market details and categories |

### 7.2 Python SDK: `py-clob-client`

Polymarket provides an official Python client:

```bash
pip install py-clob-client
```

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

# Initialize
client = ClobClient(
    host="https://clob.polymarket.com",
    key=PRIVATE_KEY,          # Ethereum private key
    chain_id=137,             # Polygon mainnet
    creds=ClobClient.derive_api_creds(PRIVATE_KEY, chain_id=137)
)

# Fetch markets
markets = client.get_markets()

# Get order book
book = client.get_order_book(token_id=TOKEN_ID)

# Place a limit order
order = client.create_and_post_order(OrderArgs(
    token_id=TOKEN_ID,
    price=0.50,
    size=100,
    side="BUY",
    order_type=OrderType.GTC,
))
```

### 7.3 WebSocket for real-time data

```python
import websockets
import json

async def stream_orderbook(token_id):
    uri = f"wss://ws-subscriptions-clob.polymarket.com/ws/market"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "subscribe",
            "channel": "book",
            "assets_id": token_id
        }))
        async for msg in ws:
            data = json.loads(msg)
            process_book_update(data)
```

### 7.4 Recommended tech stack

```
Language:     Python 3.11+
SDK:          py-clob-client (official Polymarket client)
Web3:         web3.py or eth-account (signing, wallet ops)
Async:        asyncio + aiohttp (concurrent API calls)
WebSocket:    websockets library
Data:         pandas, numpy (analysis)
Database:     SQLite or PostgreSQL (trade log, state persistence)
Scheduling:   APScheduler or custom event loop
Monitoring:   logging + alerting (Slack/Discord webhooks)
Deployment:   Docker container on a VPS (low-latency)
```

### 7.5 Key data structures

**Market object** (from Gamma API):
```json
{
  "id": "0x...",
  "question": "Will X happen by Y date?",
  "outcomes": ["Yes", "No"],
  "outcomePrices": ["0.65", "0.35"],
  "volume": "1500000",
  "liquidity": "50000",
  "endDate": "2026-06-01T00:00:00Z",
  "active": true,
  "closed": false,
  "tokens": [
    {"token_id": "abc123...", "outcome": "Yes"},
    {"token_id": "def456...", "outcome": "No"}
  ]
}
```

**Order book** (from CLOB):
```json
{
  "bids": [
    {"price": "0.63", "size": "300"},
    {"price": "0.62", "size": "450"}
  ],
  "asks": [
    {"price": "0.65", "size": "200"},
    {"price": "0.66", "size": "500"}
  ]
}
```

---

## 8. Risk Management

### Position sizing rules

| Rule | Description |
|------|-------------|
| **Max position per market** | Never risk more than X% of bankroll on one market (e.g., 5-10%) |
| **Kelly fraction** | Use half-Kelly or quarter-Kelly, never full Kelly |
| **Correlation limits** | Don't load up on correlated markets (e.g., 5 election markets that all depend on the same outcome) |
| **Drawdown circuit breaker** | If bankroll drops X% (e.g., 20%), pause trading and review |

### Inventory management (for market makers)

```
max_inventory = BANKROLL * MAX_INVENTORY_PCT / mid_price

if abs(current_inventory) > max_inventory:
    # Stop quoting on the side that increases inventory
    # Or aggressively skew quotes to flatten
```

### Common failure modes

| Failure | Cause | Mitigation |
|---------|-------|------------|
| **Picked off** | Stale quotes during fast price moves | Use WebSocket for real-time updates; cancel orders on large price moves |
| **Inventory blowup** | One-sided flow | Hard inventory limits; quote skewing; hedging on NO side |
| **API outage** | Polymarket API goes down | Graceful degradation; cancel all open orders on disconnect |
| **Fat finger** | Bug places wrong order | Sanity checks on size/price; paper trading first |
| **Rug pull** | Market resolves unexpectedly | Diversification; read resolution criteria carefully |
| **Fee change** | Fee structure changes | Monitor announcements; parameterize fees in your code |

### Order management hygiene

- **Always cancel stale orders** — Don't leave old limit orders sitting in the book when your model has moved
- **Idempotent order IDs** — Use unique client order IDs to avoid duplicate submissions
- **Reconciliation** — Periodically verify your local state matches the exchange's view of your positions
- **Graceful shutdown** — On crash/restart, cancel all open orders first, then reconstruct state

---

## 9. Analyzing Another Trader's Bot

To reverse-engineer the strategy behind `https://polymarket.com/@k9Q2mX4L8A7ZP3R`:

### Step 1: Profile analysis

Look at their public profile for:
- **Total volume** and **P&L** — Is this a high-volume low-margin bot (market maker) or a selective high-conviction bot?
- **Number of markets** — Do they trade everything or focus on specific categories?
- **Win rate** — High win rate (>60%) with small profits suggests market making. Lower win rate with large wins suggests directional/model-based.
- **Position sizes** — Uniform sizes suggest systematic; varying sizes suggest conviction-weighted.

### Step 2: Trade pattern analysis

Pull their public trade history and analyze:

```python
# Patterns to look for:
# 1. Timing — Do they trade at specific times? (news-reactive)
# 2. Speed — How fast do they enter after market creation? (first-mover)
# 3. Pairs — Do they buy YES and NO simultaneously? (arbitrage)
# 4. Holding period — Minutes (scalping), hours (swing), days (position)?
# 5. Market selection — What markets do they trade? Any pattern?
# 6. Entry price — Do they buy at round numbers? Near-extremes?
# 7. Order type — Maker or taker? (visible in fee structure)
```

### Step 3: On-chain analysis

Their wallet address is public. You can:
- Track all transactions on Polygonscan
- See token balances (what positions they hold)
- Analyze transaction timing relative to market events
- See if they interact with other contracts (DeFi, bridges, etc.)

### Step 4: Hypothesis testing

Form hypotheses about their strategy and test them:
- "They're a market maker" → Check if they have orders on both sides of the book
- "They're an arb bot" → Check if they trade both YES and NO in the same market
- "They're news-reactive" → Check trade timing vs. news events
- "They use a model" → Check if they consistently buy/sell at specific probability thresholds

### Step 5: Replication

Once you've identified the likely strategy:
1. Build a simplified version
2. Paper trade (simulate without real money) against historical data
3. Compare your simulated P&L to theirs
4. Iterate on parameters until behavior matches
5. Deploy with small real capital
6. Scale up gradually

---

## 10. Learning Path & Resources

### Phase 1: Foundations (Week 1-2)

- [ ] **Read**: Polymarket docs — [docs.polymarket.com](https://docs.polymarket.com)
- [ ] **Read**: "Trading and Exchanges" by Larry Harris (chapters on market making, order types, market microstructure)
- [ ] **Do**: Set up a Polygon wallet, get testnet USDC, make manual trades on Polymarket
- [ ] **Do**: Pull market data from the Gamma API and CLOB API using Python
- [ ] **Read**: Understand the Conditional Token Framework (Gnosis docs)

### Phase 2: Trading Concepts (Week 2-3)

- [ ] **Study**: Expected value, Kelly criterion, Bayesian updating
- [ ] **Study**: Order book mechanics, market microstructure
- [ ] **Study**: Basic market making (Avellaneda-Stoikov paper or summaries)
- [ ] **Do**: Build a data pipeline — stream order books via WebSocket, store in a database
- [ ] **Do**: Analyze order book snapshots, calculate spreads, depth, and imbalance

### Phase 3: Bot Development (Week 3-5)

- [ ] **Build**: Basic arb scanner (sum-to-one detection across all markets)
- [ ] **Build**: Simple market maker for a low-volume market (wide spreads)
- [ ] **Build**: Order management system (place, cancel, track fills)
- [ ] **Build**: Inventory tracking and P&L calculation
- [ ] **Paper trade**: Run strategies against live data without real execution

### Phase 4: Analysis & Deployment (Week 5-7)

- [ ] **Analyze**: The target trader's profile — extract trade history, identify patterns
- [ ] **Build**: Replicate identified strategy
- [ ] **Test**: Paper trade your replica against live markets
- [ ] **Deploy**: Small capital ($50-200), monitor closely
- [ ] **Iterate**: Compare your results to theirs, tune parameters, scale

### Key resources

| Resource | What it covers |
|----------|---------------|
| [docs.polymarket.com](https://docs.polymarket.com) | Official API docs, quickstart, market data |
| [github.com/Polymarket/py-clob-client](https://github.com/Polymarket/py-clob-client) | Official Python SDK |
| [github.com/Polymarket/clob-order-utils](https://github.com/Polymarket/clob-order-utils) | Order signing utilities |
| "Trading and Exchanges" — Larry Harris | Market microstructure bible |
| "Algorithmic Trading" — Ernest Chan | Practical quant strategies |
| "The Kelly Capital Growth Investment Criterion" — MacLean et al | Position sizing theory |
| Avellaneda-Stoikov (2008) paper | Market making framework |
| Gnosis Conditional Token Framework docs | Underlying token mechanics |
| Polygonscan.com | On-chain transaction analysis |

### Glossary

| Term | Definition |
|------|-----------|
| **CLOB** | Central Limit Order Book — the matching engine |
| **CTF** | Conditional Token Framework — the on-chain token standard |
| **USDC** | USD Coin — stablecoin used for trading |
| **Maker** | Trader who adds liquidity (resting limit order) |
| **Taker** | Trader who removes liquidity (crosses the spread) |
| **Spread** | Difference between best bid and best ask |
| **Slippage** | Price worsening from your order impacting the book |
| **Adverse selection** | Getting filled by informed traders who know the price is moving against you |
| **Inventory** | Your net directional position (e.g., net long 500 YES shares) |
| **Edge** | Your expected profit per trade, expressed as probability difference |
| **EV** | Expected Value — probability-weighted average outcome |
| **Sharpe** | Risk-adjusted return metric (higher = better) |
| **Drawdown** | Peak-to-trough decline in portfolio value |
| **Resolution** | When a market's outcome is determined and contracts settle |
| **Gas** | Transaction fee on Polygon (paid in MATIC) |
