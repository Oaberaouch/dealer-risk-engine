# packages/core/data/providers/router.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from packages.core.schemas.market import UnderlyingSnapshot
from packages.core.data.providers.polygon import PolygonProvider, PolygonError


ProviderName = Literal["polygon"]


@dataclass
class ProviderRouter:
    """
    Small router for provider selection.
    Extend later with options chain providers, OPRA, etc.
    """

    polygon: PolygonProvider

    @classmethod
    def from_env(cls) -> "ProviderRouter":
        return cls(polygon=PolygonProvider.from_env())

    def get_spot(self, symbol: str, provider: ProviderName = "polygon") -> UnderlyingSnapshot:
        if provider == "polygon":
            return self.polygon.get_spot(symbol)
        # Should never happen due to typing, but keep safe:
        raise ValueError(f"Unknown provider: {provider}")