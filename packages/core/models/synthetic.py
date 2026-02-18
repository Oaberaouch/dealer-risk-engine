from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import numpy as np

from packages.core.schemas.market import UnderlyingSnapshot, OptionContract, OptionChainSnapshot


@dataclass
class SyntheticConfig:
    symbol: str = "SPY"
    spot: float = 500.0

    # for RV path
    days: int = 30
    daily_mu: float = 0.0
    daily_sigma: float = 0.012  # ~19% annualized (0.012 * sqrt(252))

    # for option chain
    expiry_days: int = 30
    strikes_pct_range: float = 0.12  # +/- 12% around spot
    strikes_count: int = 41  # odd number so ATM exists
    base_iv: float = 0.18
    skew: float = 0.35  # put-skew intensity
    smile: float = 0.15  # curvature

    # micro/positioning inputs
    base_oi: int = 5000
    oi_decay: float = 0.12  # how fast OI drops away from ATM

    # rates/div yield (kept simple)
    r: float = 0.05
    q: float = 0.0


def generate_underlying_path(cfg: SyntheticConfig, seed: int = 42) -> np.ndarray:
    """
    Returns array of prices of length cfg.days+1, ending at cfg.spot (approx).
    """
    rng = np.random.default_rng(seed)
    rets = cfg.daily_mu + cfg.daily_sigma * rng.standard_normal(cfg.days)
    prices = np.empty(cfg.days + 1, dtype=float)
    prices[0] = cfg.spot
    for i in range(cfg.days):
        prices[i + 1] = prices[i] * np.exp(rets[i])
    return prices


def generate_option_chain(cfg: SyntheticConfig, seed: int = 42) -> OptionChainSnapshot:
    rng = np.random.default_rng(seed)

    ts = datetime.now(timezone.utc)
    underlying = UnderlyingSnapshot(symbol=cfg.symbol, spot=float(cfg.spot), ts=ts)

    # strikes evenly spaced around spot
    lo = cfg.spot * (1.0 - cfg.strikes_pct_range)
    hi = cfg.spot * (1.0 + cfg.strikes_pct_range)
    strikes = np.linspace(lo, hi, cfg.strikes_count)

    contracts = []
    for K in strikes:
        m = (K / cfg.spot) - 1.0  # moneyness offset

        # simple skewed smile:
        # puts richer when K < S, calls slightly cheaper
        skew_term = cfg.skew * max(0.0, -m)  # only for puts (downside)
        smile_term = cfg.smile * (m * m)

        # base IV + components + small noise
        iv_common = max(0.01, cfg.base_iv + skew_term + smile_term + 0.005 * rng.standard_normal())

        # OI concentrated near ATM, decays away
        dist = abs(m) / cfg.strikes_pct_range
        oi = int(cfg.base_oi * np.exp(-cfg.oi_decay * (dist * 10.0) ** 2))
        oi = max(0, oi)

        # build both call and put; make puts slightly higher IV in downside
        call_iv = float(max(0.01, iv_common * (1.0 - 0.04 * max(0.0, -m))))
        put_iv = float(max(0.01, iv_common * (1.0 + 0.08 * max(0.0, -m))))

        contracts.append(OptionContract(symbol=cfg.symbol, expiry_days=cfg.expiry_days, strike=float(K), right="C", iv=call_iv, oi=oi))
        contracts.append(OptionContract(symbol=cfg.symbol, expiry_days=cfg.expiry_days, strike=float(K), right="P", iv=put_iv, oi=oi))

    return OptionChainSnapshot(underlying=underlying, contracts=contracts)
