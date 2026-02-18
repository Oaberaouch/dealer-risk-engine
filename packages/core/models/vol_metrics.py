from __future__ import annotations
import numpy as np
from packages.core.schemas.market import OptionChainSnapshot

def realized_vol_annualized(prices: np.ndarray, trading_days: int = 252) -> float:
    """
    Annualized RV from log returns.
    """
    if len(prices) < 2:
        return 0.0
    rets = np.diff(np.log(prices))
    if rets.size == 0:
        return 0.0
    return float(np.std(rets, ddof=1) * np.sqrt(trading_days))

def atm_iv(chain: OptionChainSnapshot) -> float:
    """
    Simple ATM IV proxy: average of call/put IV at strike closest to spot.
    """
    S = chain.underlying.spot
    # pick strike closest to spot
    strikes = sorted(set([c.strike for c in chain.contracts]))
    if not strikes:
        return 0.0
    K_atm = min(strikes, key=lambda k: abs(k - S))
    ivs = [c.iv for c in chain.contracts if c.strike == K_atm]
    if not ivs:
        return 0.0
    return float(np.mean(ivs))

def variance_risk_premium(iv: float, rv: float) -> float:
    """
    VRP = IV - RV (in volatility points).
    """
    return float(iv - rv)