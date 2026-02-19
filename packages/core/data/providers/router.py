from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from packages.core.data.providers.base import MarketDataProvider, ProviderResult


@dataclass
class FallbackProvider(MarketDataProvider):
    primary: MarketDataProvider
    fallback: MarketDataProvider

    def get_chain(self, symbol: str, expiry_days: int, *, spot_hint: Optional[float] = None) -> ProviderResult:
        try:
            return self.primary.get_chain(symbol, expiry_days, spot_hint=spot_hint)
        except Exception:
            return self.fallback.get_chain(symbol, expiry_days, spot_hint=spot_hint)