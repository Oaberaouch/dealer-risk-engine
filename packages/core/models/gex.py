# packages/core/models/gex.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Callable, Literal, Optional

import numpy as np

from packages.core.schemas.market import OptionChainSnapshot
from packages.core.math.black_scholes import gamma_bs


Mode = Literal["netted", "raw"]


@dataclass(frozen=True)
class GexConfig:
    r: float = 0.05
    q: float = 0.0
    contract_multiplier: float = 100.0
    # +1 dealer long options, -1 dealer short options
    dealer_sign: int = -1

    # If True: calls +OI, puts -OI (net customer positioning proxy)
    # If False: calls +OI, puts +OI (magnitude-only diagnostic)
    use_call_put_netting: bool = True


def _T_years_from_expiry_days(expiry_days: int) -> float:
    return max(1.0 / 365.0, float(expiry_days) / 365.0)


def _signed_oi(right: str, oi: int, cfg: GexConfig) -> float:
    if not cfg.use_call_put_netting:
        return float(oi)
    return float(oi) if str(right).upper() == "C" else -float(oi)


def contract_gamma(chain: OptionChainSnapshot, cfg: GexConfig) -> List[dict]:
    """
    Per-contract gamma + gex contribution.
    gex_contract = dealer_sign * signed_OI * multiplier * S^2 * gamma
    """
    S = float(chain.underlying.spot)
    out: List[dict] = []

    for c in chain.contracts:
        T = _T_years_from_expiry_days(int(c.expiry_days))
        g = gamma_bs(S=S, K=float(c.strike), T=T, r=cfg.r, sigma=float(c.iv), q=cfg.q)
        s_oi = _signed_oi(c.right, int(c.oi), cfg)
        gex = float(cfg.dealer_sign) * float(s_oi) * cfg.contract_multiplier * (S * S) * float(g)

        out.append(
            {
                "strike": float(c.strike),
                "right": str(c.right).upper(),
                "expiry_days": int(c.expiry_days),
                "iv": float(c.iv),
                "oi": int(c.oi),
                "signed_oi": float(s_oi),
                "gamma": float(g),
                "gex": float(gex),
            }
        )
    return out


def gex_by_strike(chain: OptionChainSnapshot, cfg: GexConfig) -> Dict[float, float]:
    rows = contract_gamma(chain, cfg)
    agg: Dict[float, float] = {}
    for r in rows:
        K = float(r["strike"])
        agg[K] = agg.get(K, 0.0) + float(r["gex"])
    return dict(sorted(agg.items(), key=lambda x: x[0]))


def total_gex(chain: OptionChainSnapshot, cfg: GexConfig) -> float:
    return float(sum(gex_by_strike(chain, cfg).values()))


def total_gex_at_spot_raw(chain: OptionChainSnapshot, cfg: GexConfig, spot: float) -> float:
    """
    RAW mode: per-contract evaluation at hypothetical spot.
    """
    S = float(spot)
    out = 0.0
    for c in chain.contracts:
        T = _T_years_from_expiry_days(int(c.expiry_days))
        g = gamma_bs(S=S, K=float(c.strike), T=T, r=cfg.r, sigma=float(c.iv), q=cfg.q)
        s_oi = _signed_oi(c.right, int(c.oi), cfg)
        out += float(cfg.dealer_sign) * float(s_oi) * cfg.contract_multiplier * (S * S) * float(g)
    return float(out)


def _net_oi_by_strike(chain: OptionChainSnapshot, cfg: GexConfig) -> Dict[float, float]:
    net: Dict[float, float] = {}
    for c in chain.contracts:
        K = float(c.strike)
        net[K] = net.get(K, 0.0) + _signed_oi(c.right, int(c.oi), cfg)
    return dict(sorted(net.items(), key=lambda x: x[0]))


def total_gex_at_spot_netted(chain: OptionChainSnapshot, cfg: GexConfig, spot: float) -> float:
    """
    NETTED mode: net OI per strike first, then compute gamma once per strike.
    Smoother for profiles/plots.
    """
    S = float(spot)
    out = 0.0

    net = _net_oi_by_strike(chain, cfg)

    # Use the chain expiry (synthetic is single-expiry anyway)
    T = _T_years_from_expiry_days(int(chain.contracts[0].expiry_days)) if chain.contracts else 30.0 / 365.0

    # Pre-bucket IVs by strike for efficiency and determinism
    ivs_by_k: Dict[float, List[float]] = {}
    for c in chain.contracts:
        K = float(c.strike)
        ivs_by_k.setdefault(K, []).append(float(c.iv))

    for K, net_oi in net.items():
        ivs = ivs_by_k.get(float(K), [])
        sigma = float(np.mean(ivs)) if ivs else 0.2

        g = gamma_bs(S=S, K=float(K), T=T, r=cfg.r, sigma=sigma, q=cfg.q)
        out += float(cfg.dealer_sign) * float(net_oi) * cfg.contract_multiplier * (S * S) * float(g)

    return float(out)


def gamma_profile(
    chain: OptionChainSnapshot,
    cfg: GexConfig,
    s_min: float,
    s_max: float,
    steps: int = 121,
    mode: str = "netted",
) -> List[Tuple[float, float]]:
    if steps < 11:
        steps = 11
    grid = np.linspace(float(s_min), float(s_max), int(steps))

    m: Mode = "raw" if str(mode).lower() == "raw" else "netted"
    f = total_gex_at_spot_raw if m == "raw" else total_gex_at_spot_netted
    return [(float(S), float(f(chain, cfg, float(S)))) for S in grid]


def gamma_profile_both(
    chain: OptionChainSnapshot,
    cfg: GexConfig,
    s_min: float,
    s_max: float,
    steps: int = 121,
) -> dict:
    if steps < 11:
        steps = 11
    grid = np.linspace(float(s_min), float(s_max), int(steps))

    net = [float(total_gex_at_spot_netted(chain, cfg, float(S))) for S in grid]
    raw = [float(total_gex_at_spot_raw(chain, cfg, float(S))) for S in grid]

    return {"S": [float(S) for S in grid], "netted": net, "raw": raw}


def zero_gamma_level(
    chain: OptionChainSnapshot,
    cfg: GexConfig,
    bracket: Tuple[float, float],
    mode: str = "netted",  # "netted" or "raw"
    max_iter: int = 120,
    tol: float = 1e-6,          # absolute floor tolerance
    tol_rel: float | None = None,  # relative tolerance vs endpoint scale
) -> dict:
    """
    Bisection root solve for total_gex_at_spot_{mode}(S)=0.

    Strong contract (test-friendly):
    - gex_lo / gex_hi ALWAYS equal f(bracket[0]) / f(bracket[1]) (original endpoints).
    - If found=True => abs(f(level)) <= target where:
        target = max(tol, tol_rel * scale)   (if tol_rel provided)
        target = tol                         (otherwise)
      and "converged" is True.
    - If found=False => solver couldn't prove a root within tolerance (no sign change or max_iter).

    Diagnostics always included:
    - mode, iters, scale, target, bracket_final, reason, converged
    """

    lo0, hi0 = float(bracket[0]), float(bracket[1])
    if lo0 <= 0 or hi0 <= 0 or hi0 <= lo0:
        raise ValueError("Invalid bracket")

    mode_norm = "raw" if str(mode).lower() == "raw" else "netted"
    f = total_gex_at_spot_netted if mode_norm == "netted" else total_gex_at_spot_raw

    # Original endpoint evaluations (DO NOT mutate these)
    f_lo0 = float(f(chain, cfg, lo0))
    f_hi0 = float(f(chain, cfg, hi0))

    # Scale + target (relative tolerance is against endpoint magnitude)
    scale = float(max(abs(f_lo0), abs(f_hi0), 1.0))
    if tol_rel is None:
        target = float(tol)
    else:
        target = float(max(float(tol), float(tol_rel) * scale))

    # Working bracket
    lo, hi = lo0, hi0
    f_lo, f_hi = f_lo0, f_hi0

    def _pack(
        *,
        found: bool,
        level: float | None,
        gex_level: float | None,
        iters: int,
        reason: str,
        converged: bool,
    ) -> dict:
        return {
            "found": bool(found),
            "mode": mode_norm,
            "level": level,
            "gex_level": gex_level,
            "gex_lo": f_lo0,
            "gex_hi": f_hi0,
            "bracket_final": [float(lo), float(hi)],
            "gex_lo_final": float(f_lo),
            "gex_hi_final": float(f_hi),
            "iters": int(iters),
            "scale": scale,
            "target": target,
            "reason": reason,
            "converged": bool(converged),
        }

    # Endpoint roots (guaranteed)
    if f_lo == 0.0:
        return _pack(
            found=True,
            level=lo,
            gex_level=0.0,
            iters=0,
            reason="lo_is_root",
            converged=True,
        )
    if f_hi == 0.0:
        return _pack(
            found=True,
            level=hi,
            gex_level=0.0,
            iters=0,
            reason="hi_is_root",
            converged=True,
        )

    # No sign change => cannot guarantee a root by bisection
    if (f_lo > 0 and f_hi > 0) or (f_lo < 0 and f_hi < 0):
        return _pack(
            found=False,
            level=None,
            gex_level=None,
            iters=0,
            reason="no_sign_change",
            converged=False,
        )

    # Bisection with strong guarantee: only "found" if abs(f_mid) <= target
    for i in range(int(max_iter)):
        mid = 0.5 * (lo + hi)
        f_mid = float(f(chain, cfg, mid))

        if abs(f_mid) <= target:
            return _pack(
                found=True,
                level=float(mid),
                gex_level=float(f_mid),
                iters=i + 1,
                reason="converged",
                converged=True,
            )

        # Maintain straddle
        if (f_lo > 0 and f_mid < 0) or (f_lo < 0 and f_mid > 0):
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    # Max iterations reached without hitting target
    return _pack(
        found=False,
        level=None,
        gex_level=None,
        iters=int(max_iter),
        reason="max_iter",
        converged=False,
    )