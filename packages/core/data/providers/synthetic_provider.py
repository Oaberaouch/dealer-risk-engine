from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.data.providers.base import MarketDataProvider, ProviderResult


@dataclass
class SyntheticProvider(MarketDataProvider):
    cfg: SyntheticConfig
    seed: int = 42

    def get_chain(self, symbol: str, expiry_days: int, *, spot_hint: Optional[float] = None) -> ProviderResult:
        cfg = SyntheticConfig(
            symbol=symbol,
            spot=float(spot_hint) if spot_hint is not None else float(self.cfg.spot),
            expiry_days=int(expiry_days),
            strikes_pct_range=self.cfg.strikes_pct_range,
            strikes_count=self.cfg.strikes_count,
            base_iv=self.cfg.base_iv,
            skew=self.cfg.skew,
            smile=self.cfg.smile,
            oi_base=self.cfg.oi_base,
            oi_width=self.cfg.oi_width,
            tilt=self.cfg.tilt,
            min_share=self.cfg.min_share,
            r=self.cfg.r,
            q=self.cfg.q,
        )
        chain = generate_option_chain(cfg, seed=self.seed)
        try:
            chain.source = "synthetic"
        except Exception:
            pass
        return ProviderResult(chain=chain, source="synthetic")