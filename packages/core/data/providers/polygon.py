# packages/core/data/providers/polygon.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


class PolygonError(RuntimeError):
    pass


@dataclass(frozen=True)
class PolygonConfig:
    api_key: str
    base_url: str = "https://api.polygon.io"
    timeout_sec: int = 15


def _get_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise PolygonError(
            f"Missing environment variable: {name}. "
            f"Set it in your .env (or export it) before running."
        )
    return v


class PolygonClient:
    """
    Minimal Polygon.io client for SU-57 (starter, free-first):

    - get_spot_last(ticker): last trade price for an equity ticker
    - list_option_contracts(underlying): list option contracts (reference endpoint)

    Notes:
    - Polygon endpoints can vary by subscription (delayed vs real-time, options access).
    - We keep this client small and explicit so you can extend safely.
    """

    def __init__(self, cfg: Optional[PolygonConfig] = None) -> None:
        if cfg is None:
            cfg = PolygonConfig(api_key=_get_env("POLYGON_API_KEY"))
        self.cfg = cfg

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.cfg.base_url.rstrip('/')}{path}"
        params = dict(params or {})
        params["apiKey"] = self.cfg.api_key

        try:
            r = requests.get(url, params=params, timeout=self.cfg.timeout_sec)
        except requests.RequestException as e:
            raise PolygonError(f"Network error calling Polygon: {e}") from e

        # Polygon returns JSON for errors too, but not always.
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}

        if r.status_code >= 400:
            msg = data.get("error") or data.get("message") or str(data)
            raise PolygonError(f"Polygon HTTP {r.status_code}: {msg}")

        return data

    def get_spot_last(self, ticker: str) -> float:
        """
        Equity last trade price.

        Endpoint: /v2/last/trade/{ticker}
        """
        ticker = ticker.upper().strip()
        data = self._get(f"/v2/last/trade/{ticker}")
        # Expected: {"status":"OK","results":{"p":..., ...}}
        results = data.get("results") or {}
        p = results.get("p")
        if p is None:
            raise PolygonError(f"Unexpected response for last trade: {data}")
        return float(p)

    def list_option_contracts(
        self,
        underlying: str,
        as_of: Optional[str] = None,
        expiration_date: Optional[str] = None,
        contract_type: Optional[str] = None,  # "call" / "put"
        strike_price: Optional[float] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        List option contracts for an underlying.

        Endpoint: /v3/reference/options/contracts
        Common params:
          - underlying_ticker=SPY
          - as_of=YYYY-MM-DD
          - expiration_date=YYYY-MM-DD
          - contract_type=call|put
          - strike_price=...
          - limit=...
        """
        underlying = underlying.upper().strip()

        params: Dict[str, Any] = {
            "underlying_ticker": underlying,
            "limit": int(limit),
        }
        if as_of:
            params["as_of"] = as_of
        if expiration_date:
            params["expiration_date"] = expiration_date
        if contract_type:
            params["contract_type"] = contract_type.lower()
        if strike_price is not None:
            params["strike_price"] = float(strike_price)

        out: List[Dict[str, Any]] = []
        next_url: Optional[str] = None

        # Polygon is paginated. We follow next_url if present.
        while True:
            if next_url:
                # next_url is a full URL and already contains apiKey sometimes; but not guaranteed.
                # We re-call via requests to preserve it exactly, then inject apiKey if missing.
                url = next_url
                if "apiKey=" not in url:
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}apiKey={self.cfg.api_key}"
                try:
                    r = requests.get(url, timeout=self.cfg.timeout_sec)
                    data = r.json()
                except Exception as e:
                    raise PolygonError(f"Pagination error calling Polygon: {e}") from e

                if r.status_code >= 400:
                    msg = data.get("error") or data.get("message") or str(data)
                    raise PolygonError(f"Polygon HTTP {r.status_code}: {msg}")
            else:
                data = self._get("/v3/reference/options/contracts", params=params)

            results = data.get("results") or []
            if not isinstance(results, list):
                raise PolygonError(f"Unexpected contracts response: {data}")

            out.extend(results)

            next_url = data.get("next_url")
            if not next_url:
                break

            # Safety: don’t loop forever if Polygon keeps returning next_url
            if len(out) > 200_000:
                raise PolygonError("Too many option contracts returned; aborting pagination.")

        return out# packages/core/data/providers/polygon.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


class PolygonError(RuntimeError):
    pass


@dataclass(frozen=True)
class PolygonConfig:
    api_key: str
    base_url: str = "https://api.polygon.io"
    timeout_sec: int = 15


def _get_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise PolygonError(
            f"Missing environment variable: {name}. "
            f"Set it in your .env (or export it) before running."
        )
    return v


class PolygonClient:
    """
    Minimal Polygon.io client for SU-57 (starter, free-first):

    - get_spot_last(ticker): last trade price for an equity ticker
    - list_option_contracts(underlying): list option contracts (reference endpoint)

    Notes:
    - Polygon endpoints can vary by subscription (delayed vs real-time, options access).
    - We keep this client small and explicit so you can extend safely.
    """

    def __init__(self, cfg: Optional[PolygonConfig] = None) -> None:
        if cfg is None:
            cfg = PolygonConfig(api_key=_get_env("POLYGON_API_KEY"))
        self.cfg = cfg

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.cfg.base_url.rstrip('/')}{path}"
        params = dict(params or {})
        params["apiKey"] = self.cfg.api_key

        try:
            r = requests.get(url, params=params, timeout=self.cfg.timeout_sec)
        except requests.RequestException as e:
            raise PolygonError(f"Network error calling Polygon: {e}") from e

        # Polygon returns JSON for errors too, but not always.
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}

        if r.status_code >= 400:
            msg = data.get("error") or data.get("message") or str(data)
            raise PolygonError(f"Polygon HTTP {r.status_code}: {msg}")

        return data

    def get_spot_last(self, ticker: str) -> float:
        """
        Equity last trade price.

        Endpoint: /v2/last/trade/{ticker}
        """
        ticker = ticker.upper().strip()
        data = self._get(f"/v2/last/trade/{ticker}")
        # Expected: {"status":"OK","results":{"p":..., ...}}
        results = data.get("results") or {}
        p = results.get("p")
        if p is None:
            raise PolygonError(f"Unexpected response for last trade: {data}")
        return float(p)

    def list_option_contracts(
        self,
        underlying: str,
        as_of: Optional[str] = None,
        expiration_date: Optional[str] = None,
        contract_type: Optional[str] = None,  # "call" / "put"
        strike_price: Optional[float] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        List option contracts for an underlying.

        Endpoint: /v3/reference/options/contracts
        Common params:
          - underlying_ticker=SPY
          - as_of=YYYY-MM-DD
          - expiration_date=YYYY-MM-DD
          - contract_type=call|put
          - strike_price=...
          - limit=...
        """
        underlying = underlying.upper().strip()

        params: Dict[str, Any] = {
            "underlying_ticker": underlying,
            "limit": int(limit),
        }
        if as_of:
            params["as_of"] = as_of
        if expiration_date:
            params["expiration_date"] = expiration_date
        if contract_type:
            params["contract_type"] = contract_type.lower()
        if strike_price is not None:
            params["strike_price"] = float(strike_price)

        out: List[Dict[str, Any]] = []
        next_url: Optional[str] = None

        # Polygon is paginated. We follow next_url if present.
        while True:
            if next_url:
                # next_url is a full URL and already contains apiKey sometimes; but not guaranteed.
                # We re-call via requests to preserve it exactly, then inject apiKey if missing.
                url = next_url
                if "apiKey=" not in url:
                    sep = "&" if "?" in url else "?"
                    url = f"{url}{sep}apiKey={self.cfg.api_key}"
                try:
                    r = requests.get(url, timeout=self.cfg.timeout_sec)
                    data = r.json()
                except Exception as e:
                    raise PolygonError(f"Pagination error calling Polygon: {e}") from e

                if r.status_code >= 400:
                    msg = data.get("error") or data.get("message") or str(data)
                    raise PolygonError(f"Polygon HTTP {r.status_code}: {msg}")
            else:
                data = self._get("/v3/reference/options/contracts", params=params)

            results = data.get("results") or []
            if not isinstance(results, list):
                raise PolygonError(f"Unexpected contracts response: {data}")

            out.extend(results)

            next_url = data.get("next_url")
            if not next_url:
                break

            # Safety: don’t loop forever if Polygon keeps returning next_url
            if len(out) > 200_000:
                raise PolygonError("Too many option contracts returned; aborting pagination.")

        return out