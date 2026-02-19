# packages/core/data/providers/base.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from packages.core.schemas.market import OptionChainSnapshot


@dataclass(frozen=True)
class ProviderConfig:
    symbol: str = "SPY"


class ChainProvider(Protocol):
    name: str

    def fetch_chain(self, cfg: ProviderConfig) -> OptionChainSnapshot:
        ...