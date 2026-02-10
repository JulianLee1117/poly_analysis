"""Configuration for Polymarket bot analysis."""

import os

# Target wallet
WALLET_ADDRESS = "0xd0d6053c3c37e727402d84c14069780d360993aa"
WALLET_LABEL = "Uncommon-Oat"

# API base URLs (no auth required)
DATA_API_BASE = "https://data-api.polymarket.com"
GAMMA_API_BASE = "https://gamma-api.polymarket.com"

# Rate limiting
RATE_LIMIT_REQUESTS_PER_SECOND = 5
RATE_LIMIT_BURST = 10

# Pagination
PAGE_SIZE = 1000  # API max — tested, returns up to 1000
MAX_OFFSET = 3000  # API hard limit — use backward timestamp windowing beyond this

# Retry / backoff
MAX_RETRIES = 5
BACKOFF_BASE = 1.0  # seconds
BACKOFF_FACTOR = 2.0

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
DB_PATH = os.path.join(DATA_DIR, "polymarket.db")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# Market metadata batch size (for Gamma API condition_ids param)
MARKET_BATCH_SIZE = 20

# Polygon RPC (on-chain data collection)
POLYGON_RPC_URL = os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com")
POLYGON_RPC_RATE_LIMIT = float(os.environ.get("POLYGON_RPC_RATE_LIMIT", "2.0"))
POLYGON_RPC_BURST = 3
POLYGON_RPC_BATCH_SIZE = 3000  # blocks per eth_getLogs call
POLYGON_RPC_MAX_RETRIES = 5

# CTF Exchange contracts (Polymarket on Polygon)
CTF_EXCHANGE_ADDRESS = "0x4bfb41d5b3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEGRISK_CTF_EXCHANGE_ADDRESS = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
