# packages/core/data/providers/synthetic_provider.py
from __future__ import annotations

from dataclasses import dataclass

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.data.providers.base import ChainProvider, ProviderConfig


@dataclass(frozen=True)
class SyntheticProvider(ChainProvider):
    name: str = "synthetic"

    # expose the same knobs you already use
    spot: float = 500.0
    expiry_days: int = 30
    base_iv: float = 0.18
    strikes_pct_range: float = 0.12
    strikes_count: int = 41
    skew: float = 0.35
    smile: float = 0.15
    oi_base: int = 12000
    oi_width: float = 0.12
    tilt: float = 2.0
    min_share: float = 0.10
    seed: int = 42

    def fetch_chain(self, cfg: ProviderConfig):
        syn = SyntheticConfig(
            symbol=cfg.symbol,
            spot=self.spot,
            expiry_days=self.expiry_days,
            base_iv=self.base_iv,
            strikes_pct_range=self.strikes_pct_range,
            strikes_count=self.strikes_count,
            skew=self.skew,
            smile=self.smile,
            oi_base=self.oi_base,
            oi_width=self.oi_width,
            tilt=self.tilt,
            min_share=self.min_share,
        )
        return generate_option_chain(syn, seed=self.seed)