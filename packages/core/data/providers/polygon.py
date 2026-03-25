# packages/core/data/providers/polygon.py
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx

from packages.core.schemas.market import UnderlyingSnapshot


class PolygonError(RuntimeError):
    pass


@dataclass
class PolygonProvider:
    """
    Polygon spot provider with free-tier fallback.

    Primary (best): last trade (often restricted on free tiers)
      GET /v2/last/trade/{ticker}

    Fallback (usually available on basic/free for stocks): previous close (EOD proxy)
      GET /v2/aggs/ticker/{ticker}/prev
    """

    api_key: str
    base_url: str = "https://api.polygon.io"
    timeout_s: float = 10.0

    @classmethod
    def from_env(cls) -> "PolygonProvider":
        key = os.getenv("POLYGON_API_KEY", "").strip()
        if not key:
            raise PolygonError("POLYGON_API_KEY is not set (check .env and load_dotenv).")
        return cls(api_key=key)

    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        q = dict(params or {})
        q["apiKey"] = self.api_key

        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                r = client.get(url, params=q)
        except Exception as e:
            raise PolygonError(f"Polygon request failed: {e}") from e

        if r.status_code != 200:
            # Keep payload for debugging
            raise PolygonError(f"Polygon HTTP {r.status_code}: {r.text}")

        try:
            return r.json()
        except Exception as e:
            raise PolygonError(f"Polygon JSON decode failed: {e}") from e

    @staticmethod
    def _is_not_authorized(err: Exception) -> bool:
        s = str(err)
        return ("HTTP 403" in s) or ("NOT_AUTHORIZED" in s) or ("not entitled" in s.lower())

    def get_last_trade(self, symbol: str) -> UnderlyingSnapshot:
        """
        STRICT real-time last trade endpoint. May 403 on free/basic plans.
        """
        symbol = symbol.upper().strip()
        data = self._get_json(f"/v2/last/trade/{symbol}")

        results = data.get("results") or {}
        price = results.get("p")
        ts_ms = results.get("t")

        if price is None:
            raise PolygonError(f"Polygon last-trade response missing price. Payload={data}")

        if ts_ms is None:
            ts = datetime.now(timezone.utc)
        else:
            ts = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)

        return UnderlyingSnapshot(symbol=symbol, spot=float(price), ts=ts)

    def get_prev_close(self, symbol: str) -> UnderlyingSnapshot:
        """
        Previous close (EOD proxy spot). Often available on free/basic.
        """
        symbol = symbol.upper().strip()
        data = self._get_json(f"/v2/aggs/ticker/{symbol}/prev")

        # Expected shape:
        # {"status":"OK","resultsCount":1,"results":[{"T":"SPY","c":500.12,"t":...}]}
        results = data.get("results") or []
        if not results:
            raise PolygonError(f"Polygon prev-close response missing results. Payload={data}")

        row = results[0] or {}
        close_px = row.get("c")
        ts_ms = row.get("t")

        if close_px is None:
            raise PolygonError(f"Polygon prev-close response missing close price. Payload={data}")

        if ts_ms is None:
            ts = datetime.now(timezone.utc)
        else:
            ts = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)

        return UnderlyingSnapshot(symbol=symbol, spot=float(close_px), ts=ts)

    def get_spot_best_effort(self, symbol: str) -> Tuple[UnderlyingSnapshot, str]:
        """
        Best-effort spot:
        1) Try last trade
        2) If blocked, fall back to prev close
        Returns (snapshot, source_tag)
        """
        try:
            snap = self.get_last_trade(symbol)
            return snap, "last_trade"
        except Exception as e:
            if self._is_not_authorized(e):
                snap = self.get_prev_close(symbol)
                return snap, "prev_close"
            raise

    # Backward-compatible name used by your API code:
    def get_spot(self, symbol: str) -> UnderlyingSnapshot:
        """
        Default get_spot now uses best-effort (so your /market/spot won't die on 403).
        """
        snap, _src = self.get_spot_best_effort(symbol)
        return snap