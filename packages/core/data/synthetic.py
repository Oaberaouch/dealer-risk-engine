# packages/core/data/synthetic.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Tuple

import numpy as np

from packages.core.schemas.market import UnderlyingSnapshot, OptionContract, OptionChainSnapshot


@dataclass
class SyntheticConfig:
    symbol: str = "SPY"
    spot: float = 500.0

    # option chain surface
    expiry_days: int = 30
    strikes_pct_range: float = 0.12  # +/- around spot
    strikes_count: int = 41          # odd preferred
    base_iv: float = 0.18
    skew: float = 0.35              # downside richer
    smile: float = 0.15             # curvature

    # open interest (OI) shape controls
    oi_base: int = 12000            # baseline OI scale
    oi_width: float = 0.12          # how wide OI distribution is (fraction of spot range)
    tilt: float = 2.0               # >0 shifts OI toward calls above spot and puts below spot
    min_share: float = 0.10         # minimum share for the "weak side" (0..0.49)

    # rates/div (kept simple)
    r: float = 0.05
    q: float = 0.0


def _linspace_strikes(spot: float, pct_range: float, count: int) -> np.ndarray:
    lo = spot * (1.0 - pct_range)
    hi = spot * (1.0 + pct_range)
    return np.linspace(lo, hi, int(count))


def _iv_smile_skew(
    spot: float,
    K: float,
    base_iv: float,
    skew: float,
    smile: float,
    noise: float,
) -> float:
    """
    Simple skewed smile:
    - puts richer when K < S
    - mild curvature on both sides
    """
    m = (K / spot) - 1.0
    skew_term = skew * max(0.0, -m)          # only downside
    smile_term = smile * (m * m)
    iv = base_iv + skew_term + smile_term + noise
    return float(max(0.01, iv))


def _oi_envelope(spot: float, K: float, pct_range: float, oi_base: int, oi_width: float) -> float:
    """
    Smooth bell-ish envelope concentrated around ATM.
    """
    # normalize distance from spot into ~[-1, 1] by pct_range
    x = ((K / spot) - 1.0) / max(1e-9, pct_range)
    # width controls how fast it decays: smaller width => narrower peak
    w = max(1e-6, oi_width / max(1e-6, pct_range))
    # gaussian-like envelope
    env = np.exp(-0.5 * (x / w) ** 2)
    return float(oi_base * env)


def _call_put_split(spot: float, K: float, tilt: float, min_share: float) -> Tuple[float, float]:
    """
    Returns (call_share, put_share) in [0,1], sum to 1.
    tilt>0:
      - for strikes above spot: more calls
      - for strikes below spot: more puts
    min_share keeps the weaker side from going to 0.
    """
    min_share = float(min(max(min_share, 0.0), 0.49))
    m = (K / spot) - 1.0

    # smooth logistic push; abs(tilt) controls steepness
    # m>0 => push to calls, m<0 => push to puts
    z = float(tilt) * float(m) * 8.0
    call_share = 1.0 / (1.0 + np.exp(-z))

    # clamp to [min_share, 1-min_share]
    call_share = float(min(max(call_share, min_share), 1.0 - min_share))
    put_share = 1.0 - call_share
    return call_share, put_share


def generate_option_chain(cfg: SyntheticConfig, seed: int = 42) -> OptionChainSnapshot:
    rng = np.random.default_rng(seed)

    ts = datetime.now(timezone.utc)
    underlying = UnderlyingSnapshot(symbol=cfg.symbol, spot=float(cfg.spot), ts=ts)

    strikes = _linspace_strikes(cfg.spot, cfg.strikes_pct_range, cfg.strikes_count)

    contracts = []
    for K in strikes:
        # IV (common), then nudge puts a bit richer on downside
        noise = 0.005 * float(rng.standard_normal())
        iv_common = _iv_smile_skew(cfg.spot, float(K), cfg.base_iv, cfg.skew, cfg.smile, noise)

        m = (float(K) / cfg.spot) - 1.0
        call_iv = float(max(0.01, iv_common * (1.0 - 0.04 * max(0.0, -m))))
        put_iv = float(max(0.01, iv_common * (1.0 + 0.08 * max(0.0, -m))))

        # OI: envelope * split into call vs put using tilt
        total_oi = _oi_envelope(cfg.spot, float(K), cfg.strikes_pct_range, cfg.oi_base, cfg.oi_width)
        call_share, put_share = _call_put_split(cfg.spot, float(K), cfg.tilt, cfg.min_share)

        call_oi = int(round(total_oi * call_share))
        put_oi = int(round(total_oi * put_share))
        call_oi = max(0, call_oi)
        put_oi = max(0, put_oi)

        contracts.append(
            OptionContract(
                symbol=cfg.symbol,
                expiry_days=int(cfg.expiry_days),
                strike=float(K),
                right="C",
                iv=call_iv,
                oi=call_oi,
            )
        )
        contracts.append(
            OptionContract(
                symbol=cfg.symbol,
                expiry_days=int(cfg.expiry_days),
                strike=float(K),
                right="P",
                iv=put_iv,
                oi=put_oi,
            )
        )

    return OptionChainSnapshot(underlying=underlying, contracts=contracts)