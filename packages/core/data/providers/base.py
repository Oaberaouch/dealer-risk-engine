from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from packages.core.schemas.market import OptionChainSnapshot


@dataclass(frozen=True)
class ProviderResult:
    chain: OptionChainSnapshot
    source: str  # "tradier" | "synthetic"


class MarketDataProvider(Protocol):
    def get_chain(self, symbol: str, expiry_days: int, *, spot_hint: Optional[float] = None) -> ProviderResult:
        ...