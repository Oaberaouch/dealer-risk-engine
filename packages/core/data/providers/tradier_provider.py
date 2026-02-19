from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from packages.core.data.providers.base import MarketDataProvider, ProviderResult
from packages.core.schemas.market import UnderlyingSnapshot, OptionContract, OptionChainSnapshot


class TradierError(RuntimeError):
    pass


@dataclass(frozen=True)
class TradierConfig:
    token: str
    base_url: str = "https://api.tradier.com/v1"
    timeout_s: float = 10.0


@dataclass
class TradierProvider(MarketDataProvider):
    cfg: TradierConfig

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.token}",
            "Accept": "application/json",
        }

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.cfg.base_url}{path}"
        try:
            with httpx.Client(timeout=self.cfg.timeout_s) as client:
                r = client.get(url, headers=self._headers(), params=params)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            raise TradierError(f"Tradier HTTP error: {e}") from e
        except ValueError as e:
            raise TradierError(f"Tradier JSON decode error: {e}") from e

    def _quote_spot(self, symbol: str) -> float:
        data = self._get("/markets/quotes", {"symbols": symbol})
        q = data.get("quotes", {}).get("quote")
        if q is None:
            raise TradierError("Tradier: missing quotes.quote")
        if isinstance(q, list):
            q = q[0]

        last = q.get("last")
        if last is None:
            bid = q.get("bid")
            ask = q.get("ask")
            if bid is not None and ask is not None:
                return 0.5 * (float(bid) + float(ask))
            raise TradierError("Tradier: no last/bid/ask to derive spot")
        return float(last)

    def _expirations(self, symbol: str) -> List[str]:
        data = self._get("/markets/options/expirations", {"symbol": symbol})
        dates = data.get("expirations", {}).get("date")
        if dates is None:
            raise TradierError("Tradier: missing expirations.date")
        if isinstance(dates, str):
            return [dates]
        return list(dates)

    def _pick_expiration_by_days(self, expirations: List[str], expiry_days: int) -> str:
        now = datetime.now(timezone.utc).date()

        parsed = []
        for s in expirations:
            try:
                d = datetime.fromisoformat(s).date()
            except Exception:
                continue
            days = (d - now).days
            parsed.append((days, s))

        parsed.sort(key=lambda x: x[0])

        for days, s in parsed:
            if days >= int(expiry_days):
                return s

        if not parsed:
            raise TradierError("Tradier: could not parse expirations")
        return parsed[-1][1]

    def _option_chain(self, symbol: str, expiration: str) -> List[Dict[str, Any]]:
        data = self._get("/markets/options/chains", {"symbol": symbol, "expiration": expiration, "greeks": "false"})
        opts = data.get("options", {}).get("option")
        if opts is None:
            raise TradierError("Tradier: missing options.option")
        if isinstance(opts, dict):
            return [opts]
        return list(opts)

    def get_chain(self, symbol: str, expiry_days: int, *, spot_hint: Optional[float] = None) -> ProviderResult:
        if not self.cfg.token:
            raise TradierError("Tradier token missing")

        spot = float(spot_hint) if spot_hint is not None else self._quote_spot(symbol)

        expirations = self._expirations(symbol)
        exp = self._pick_expiration_by_days(expirations, int(expiry_days))

        raw_opts = self._option_chain(symbol, exp)

        ts = datetime.now(timezone.utc)
        underlying = UnderlyingSnapshot(symbol=symbol, spot=spot, ts=ts)

        exp_date = datetime.fromisoformat(exp).date()
        calc_expiry_days = max(1, (exp_date - ts.date()).days)

        contracts: List[OptionContract] = []
        for o in raw_opts:
            right = str(o.get("option_type", "")).upper()
            right = "C" if right in ("CALL", "C") else "P"

            strike = float(o["strike"])

            iv = o.get("implied_volatility")
            if iv is None:
                iv = 0.20
            iv = float(iv)

            oi = o.get("open_interest")
            oi = int(oi) if oi is not None else 0

            contracts.append(
                OptionContract(
                    symbol=symbol,
                    expiry_days=int(calc_expiry_days),
                    strike=strike,
                    right=right,
                    iv=iv,
                    oi=oi,
                )
            )

        chain = OptionChainSnapshot(underlying=underlying, contracts=contracts)
        try:
            chain.source = "tradier"
        except Exception:
            pass

        return ProviderResult(chain=chain, source="tradier")