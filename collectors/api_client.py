"""Rate-limited HTTP client with caching and retry logic."""

import hashlib
import json
import os
import time
from typing import Any, Dict, Optional

import requests

import config


class RateLimitedClient:
    """HTTP client with token-bucket rate limiting, file-based caching, and exponential backoff."""

    def __init__(
        self,
        requests_per_second: float = config.RATE_LIMIT_REQUESTS_PER_SECOND,
        burst: int = config.RATE_LIMIT_BURST,
        cache_dir: Optional[str] = None,
        use_cache: bool = True,
    ):
        self.rps = requests_per_second
        self.burst = burst
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self.cache_dir = cache_dir or config.CACHE_DIR
        self.use_cache = use_cache
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "PolymarketBotAnalysis/1.0",
        })

        if self.use_cache:
            os.makedirs(self.cache_dir, exist_ok=True)

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

    def _cache_key(self, url: str, params: Optional[Dict]) -> str:
        key_str = url + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()

    def _cache_path(self, cache_key: str) -> str:
        return os.path.join(self.cache_dir, f"{cache_key}.json")

    def _read_cache(self, cache_key: str) -> Optional[Any]:
        path = self._cache_path(cache_key)
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return None

    def _write_cache(self, cache_key: str, data: Any):
        path = self._cache_path(cache_key)
        with open(path, "w") as f:
            json.dump(data, f)

    def get(
        self,
        url: str,
        params: Optional[Dict] = None,
        skip_cache: bool = False,
    ) -> Any:
        """GET request with rate limiting, caching, and retries.

        Returns parsed JSON response.
        """
        # Check cache first
        if self.use_cache and not skip_cache:
            cache_key = self._cache_key(url, params)
            cached = self._read_cache(cache_key)
            if cached is not None:
                return cached

        # Rate limit
        self._wait_for_token()

        # Retry with exponential backoff
        last_exception = None
        for attempt in range(config.MAX_RETRIES):
            try:
                resp = self.session.get(url, params=params, timeout=30)

                if resp.status_code == 429:
                    wait = config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** attempt)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                # Cache the successful response
                if self.use_cache and not skip_cache:
                    self._write_cache(cache_key, data)

                return data

            except requests.exceptions.HTTPError as e:
                if resp.status_code in (500, 502, 503, 504):
                    last_exception = e
                    wait = config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** attempt)
                    time.sleep(wait)
                    continue
                raise
            except requests.exceptions.RequestException as e:
                last_exception = e
                wait = config.BACKOFF_BASE * (config.BACKOFF_FACTOR ** attempt)
                time.sleep(wait)
                continue

        raise last_exception or RuntimeError(f"Failed after {config.MAX_RETRIES} retries: {url}")
