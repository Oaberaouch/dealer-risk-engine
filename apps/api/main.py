# apps/api/main.py
from dotenv import load_dotenv
load_dotenv()
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, Query

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.models.gex import (
    GexConfig,
    gex_by_strike,
    total_gex,
    gamma_profile,
    gamma_profile_both,
    zero_gamma_level,
    total_gex_at_spot_netted,
    total_gex_at_spot_raw,
)

# NEW: provider layer (used only by /market/* endpoints)
from packages.core.data.providers.synthetic_provider import SyntheticProvider
from packages.core.data.providers.tradier_provider import TradierConfig, TradierProvider
from packages.core.data.providers.router import FallbackProvider

app = FastAPI(title="SU-57 (Synthetic SPY) API", version="0.3.0")


@app.get("/health")
def health():
    return {"status": "ok"}


# -----------------------------
# Provider wiring (market only)
# -----------------------------
def _build_provider_stack() -> dict:
    tradier_token = os.getenv("TRADIER_TOKEN", "").strip()
    tradier = TradierProvider(TradierConfig(token=tradier_token)) if tradier_token else None
    return {"tradier": tradier}


_PROVIDER_SINGLETON = _build_provider_stack()


# -----------------------------
# Helpers
# -----------------------------
def _make_synth_cfg(
    spot: float,
    expiry_days: int,
    base_iv: float,
    strikes_pct_range: float,
    strikes_count: int,
    skew: float,
    smile: float,
    oi_base: int,
    oi_width: float,
    tilt: float,
    min_share: float,
) -> SyntheticConfig:
    return SyntheticConfig(
        symbol="SPY",
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )


def _scale_divisor(scale: str) -> float:
    s = (scale or "raw").strip().lower()
    if s in ("raw", "1", "1.0"):
        return 1.0
    if s in ("k", "thousand"):
        return 1e3
    if s in ("m", "mm", "million"):
        return 1e6
    if s in ("b", "bn", "billion"):
        return 1e9
    if s in ("t", "tn", "trillion"):
        return 1e12
    # fallback: raw
    return 1.0


# -----------------------------
# Synthetic endpoints (unchanged surface)
# -----------------------------
@app.get("/synthetic/chain")
def synthetic_chain(
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    chain = generate_option_chain(cfg, seed=seed)

    ts = getattr(chain.underlying, "ts", None)
    ts_out = ts.isoformat() if ts is not None else None

    return {
        "symbol": chain.underlying.symbol,
        "spot": chain.underlying.spot,
        "timestamp": ts_out,
        "params": {
            "expiry_days": expiry_days,
            "base_iv": base_iv,
            "strikes_pct_range": strikes_pct_range,
            "strikes_count": strikes_count,
            "skew": skew,
            "smile": smile,
            "oi_base": oi_base,
            "oi_width": oi_width,
            "tilt": tilt,
            "min_share": min_share,
            "seed": seed,
        },
        "contracts": [
            {
                "strike": c.strike,
                "right": c.right,
                "expiry_days": c.expiry_days,
                "iv": c.iv,
                "oi": c.oi,
            }
            for c in chain.contracts
        ],
    }


@app.get("/synthetic/gex")
def synthetic_gex(
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    dealer_sign: int = Query(-1),
    use_call_put_netting: bool = Query(True),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    chain = generate_option_chain(cfg_syn, seed=seed)

    cfg = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=use_call_put_netting)
    by_strike = gex_by_strike(chain, cfg)
    tot = total_gex(chain, cfg)

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "dealer_sign": dealer_sign,
        "use_call_put_netting": use_call_put_netting,
        "total_gex": tot,
        "gex_by_strike": by_strike,
        "notes": {
            "dealer_sign": "-1 assumes dealers are net short customer positioning.",
            "call_put_netting": "If true: calls +OI, puts -OI before dealer_sign.",
            "gex_units": "OI * multiplier * S^2 * gamma",
        },
    }


@app.get("/synthetic/zero-gamma")
def synthetic_zero_gamma(
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    bracket_pct: float = Query(0.25, gt=0.02, le=0.80),
    dealer_sign: int = Query(-1),
    use_call_put_netting: bool = Query(True),
    mode: str = Query("netted"),  # "netted" or "raw"
    tol_rel: float = Query(1e-6, gt=0.0, lt=1e-1),
    max_iter: int = Query(140, ge=10, le=500),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    chain = generate_option_chain(cfg_syn, seed=seed)

    cfg = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=use_call_put_netting)
    lo = spot * (1.0 - bracket_pct)
    hi = spot * (1.0 + bracket_pct)

    mode = "raw" if mode.lower() == "raw" else "netted"
    res = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode=mode, tol_rel=tol_rel, max_iter=max_iter)

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "bracket": [lo, hi],
        "dealer_sign": dealer_sign,
        "use_call_put_netting": use_call_put_netting,
        "mode": mode,
        "tol_rel": float(tol_rel),
        "max_iter": int(max_iter),
        "synthetic_params": {
            "base_iv": base_iv,
            "strikes_pct_range": strikes_pct_range,
            "strikes_count": strikes_count,
            "skew": skew,
            "smile": smile,
            "oi_base": oi_base,
            "oi_width": oi_width,
            "tilt": tilt,
            "min_share": min_share,
            "seed": seed,
        },
        "result": res,
    }


@app.get("/synthetic/zero-gamma/compare")
def synthetic_zero_gamma_compare(
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    bracket_pct: float = Query(0.25, gt=0.02, le=0.80),
    dealer_sign: int = Query(-1),
    tol_rel: float = Query(1e-6, gt=0.0, lt=1e-1),
    max_iter: int = Query(140, ge=10, le=500),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    chain = generate_option_chain(cfg_syn, seed=seed)

    # Compare using a consistent signed OI convention (calls +, puts -).
    cfg = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=True)

    lo = spot * (1.0 - bracket_pct)
    hi = spot * (1.0 + bracket_pct)

    netted = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="netted", tol_rel=tol_rel, max_iter=max_iter)
    raw = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="raw", tol_rel=tol_rel, max_iter=max_iter)

    both_found = bool(netted.get("found") and raw.get("found"))
    level_diff = (float(netted["level"]) - float(raw["level"])) if both_found else None

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "bracket": [lo, hi],
        "dealer_sign": dealer_sign,
        "tol_rel": float(tol_rel),
        "max_iter": int(max_iter),
        "synthetic_params": {
            "base_iv": base_iv,
            "strikes_pct_range": strikes_pct_range,
            "strikes_count": strikes_count,
            "skew": skew,
            "smile": smile,
            "oi_base": oi_base,
            "oi_width": oi_width,
            "tilt": tilt,
            "min_share": min_share,
            "seed": seed,
        },
        "netted": {"mode": "netted", "use_call_put_netting": True, "result": netted},
        "raw": {"mode": "raw", "use_call_put_netting": True, "result": raw},
        "delta": {"both_found": both_found, "level_diff": level_diff},
        "interpretation": {
            "netted": "Net-by-strike tends to be smoother and more stable for profiles/plots.",
            "raw": "Per-contract signed OI is a direct calculation; use it as a diagnostic and sanity check.",
        },
    }


@app.get("/synthetic/gamma-profile")
def synthetic_gamma_profile(
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    span_pct: float = Query(0.25, gt=0.02, le=0.80),
    steps: int = Query(121, ge=31, le=401),
    dealer_sign: int = Query(-1),
    use_call_put_netting: bool = Query(True),
    mode: str = Query("netted"),  # "netted" or "raw"
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    chain = generate_option_chain(cfg_syn, seed=seed)

    cfg = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=use_call_put_netting)
    s_min = spot * (1.0 - span_pct)
    s_max = spot * (1.0 + span_pct)

    mode = "raw" if mode.lower() == "raw" else "netted"
    prof = gamma_profile(chain, cfg, s_min=s_min, s_max=s_max, steps=steps, mode=mode)

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "range": [s_min, s_max],
        "steps": steps,
        "dealer_sign": dealer_sign,
        "use_call_put_netting": use_call_put_netting,
        "mode": mode,
        "S": [p[0] for p in prof],
        "GEX": [p[1] for p in prof],
    }


@app.get("/synthetic/gamma-profile/compare")
def synthetic_gamma_profile_compare(
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    span_pct: float = Query(0.25, gt=0.02, le=0.80),
    steps: int = Query(121, ge=31, le=401),
    dealer_sign: int = Query(-1),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    chain = generate_option_chain(cfg_syn, seed=seed)

    # compare requires call/put sign netting enabled
    cfg = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=True)

    s_min = spot * (1.0 - span_pct)
    s_max = spot * (1.0 + span_pct)

    prof = gamma_profile_both(chain, cfg, s_min=s_min, s_max=s_max, steps=steps)

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "range": [s_min, s_max],
        "steps": steps,
        "dealer_sign": dealer_sign,
        "synthetic_params": {
            "base_iv": base_iv,
            "strikes_pct_range": strikes_pct_range,
            "strikes_count": strikes_count,
            "skew": skew,
            "smile": smile,
            "oi_base": oi_base,
            "oi_width": oi_width,
            "tilt": tilt,
            "min_share": min_share,
            "seed": seed,
        },
        "S": prof["S"],
        "GEX_netted": prof["netted"],
        "GEX_raw": prof["raw"],
    }


@app.get("/synthetic/summary")
def synthetic_summary(
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    bracket_pct: float = Query(0.40, gt=0.02, le=0.80),
    span_pct: float = Query(0.40, gt=0.02, le=0.80),
    steps: int = Query(121, ge=31, le=401),
    dealer_sign: int = Query(-1),
    scale: str = Query("raw"),  # raw|k|m|b|t
    seed: int = Query(42, ge=0, le=10_000),
):
    """
    Single "sanity" endpoint:
    - zero-gamma (netted vs raw)
    - sign at spot (netted vs raw)
    - max/min over a span for both
    - most influential strike by |net OI| (calls - puts)
    - optional scaling for readability
    """
    cfg_syn = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    chain = generate_option_chain(cfg_syn, seed=seed)

    lo = spot * (1.0 - bracket_pct)
    hi = spot * (1.0 + bracket_pct)

    cfg_common = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=True)

    zg_netted = zero_gamma_level(chain, cfg_common, bracket=(lo, hi), mode="netted")
    zg_raw = zero_gamma_level(chain, cfg_common, bracket=(lo, hi), mode="raw")

    s_min = spot * (1.0 - span_pct)
    s_max = spot * (1.0 + span_pct)

    prof = gamma_profile_both(chain, cfg_common, s_min=s_min, s_max=s_max, steps=steps)
    S_grid = prof["S"]
    gex_netted = prof["netted"]
    gex_raw = prof["raw"]

    def _sign(x: float) -> str:
        if x > 0:
            return "positive"
        if x < 0:
            return "negative"
        return "zero"

    # nearest grid point to spot
    if S_grid:
        idx = min(range(len(S_grid)), key=lambda i: abs(float(S_grid[i]) - float(spot)))
        nearest_S = float(S_grid[idx])
        g_spot_netted = float(gex_netted[idx])
        g_spot_raw = float(gex_raw[idx])
    else:
        nearest_S = float(spot)
        g_spot_netted = float(total_gex_at_spot_netted(chain, cfg_common, float(spot)))
        g_spot_raw = float(total_gex_at_spot_raw(chain, cfg_common, float(spot)))

    # extrema
    net_max = float(max(gex_netted)) if gex_netted else 0.0
    net_min = float(min(gex_netted)) if gex_netted else 0.0
    raw_max = float(max(gex_raw)) if gex_raw else 0.0
    raw_min = float(min(gex_raw)) if gex_raw else 0.0

    net_max_S = float(S_grid[int(max(range(len(gex_netted)), key=lambda i: gex_netted[i]))]) if gex_netted else None
    net_min_S = float(S_grid[int(min(range(len(gex_netted)), key=lambda i: gex_netted[i]))]) if gex_netted else None
    raw_max_S = float(S_grid[int(max(range(len(gex_raw)), key=lambda i: gex_raw[i]))]) if gex_raw else None
    raw_min_S = float(S_grid[int(min(range(len(gex_raw)), key=lambda i: gex_raw[i]))]) if gex_raw else None

    # most influential strike by |net OI| (calls - puts)
    net_oi_by_strike = {}
    for c in chain.contracts:
        K = float(c.strike)
        sgn = 1.0 if str(c.right).upper() == "C" else -1.0
        net_oi_by_strike[K] = net_oi_by_strike.get(K, 0.0) + sgn * float(c.oi)

    if net_oi_by_strike:
        k_star = max(net_oi_by_strike.items(), key=lambda kv: abs(kv[1]))[0]
        k_star_val = float(net_oi_by_strike[k_star])
    else:
        k_star = None
        k_star_val = 0.0

    div = float(_scale_divisor(scale))

    def _scaled(x: Optional[float]) -> Optional[float]:
        if x is None:
            return None
        return float(x) / div

    # scale zero-gamma endpoint values (gex_lo/gex_hi are typically small; still scale consistently)
    def _scale_zg(res: dict) -> dict:
        out = dict(res)
        for k in ("gex_lo", "gex_hi", "gex_level", "gex_lo_final", "gex_hi_final", "scale", "target"):
            if k in out and out[k] is not None:
                out[k] = float(out[k]) / div
        return out

    return {
        "symbol": "SPY",
        "spot": float(spot),
        "expiry_days": int(expiry_days),
        "dealer_sign": int(dealer_sign),
        "scale": (scale or "raw"),
        "scale_divisor": div,
        "bracket": [float(lo), float(hi)],
        "range": [float(s_min), float(s_max)],
        "steps": int(steps),
        "synthetic_params": {
            "base_iv": base_iv,
            "strikes_pct_range": strikes_pct_range,
            "strikes_count": strikes_count,
            "skew": skew,
            "smile": smile,
            "oi_base": oi_base,
            "oi_width": oi_width,
            "tilt": tilt,
            "min_share": min_share,
            "seed": seed,
        },
        "zero_gamma": {
            "netted": {"mode": "netted", "result": _scale_zg(zg_netted)},
            "raw": {"mode": "raw", "result": _scale_zg(zg_raw)},
        },
        "at_spot": {
            "note": "at_spot uses the nearest S grid point from gamma_profile_both",
            "nearest_S": nearest_S,
            "netted": {"gex": _scaled(g_spot_netted), "sign": _sign(g_spot_netted)},
            "raw": {"gex": _scaled(g_spot_raw), "sign": _sign(g_spot_raw)},
        },
        "extrema_over_span": {
            "netted": {"max": _scaled(net_max), "max_S": net_max_S, "min": _scaled(net_min), "min_S": net_min_S},
            "raw": {"max": _scaled(raw_max), "max_S": raw_max_S, "min": _scaled(raw_min), "min_S": raw_min_S},
        },
        "most_influential_strike_by_abs_net_oi": {
            "strike": k_star,
            "net_oi": k_star_val,
            "definition": "net_oi(strike) = call_OI - put_OI at that strike",
        },
        "notes": {
            "expectation": "Netted and raw should be close. If they diverge a lot, inspect OI shaping and sign conventions.",
            "scaling": "All reported GEX values (including gex_lo/gex_hi, at_spot, extrema) are divided by scale_divisor.",
        },
    }


# -----------------------------
# Market endpoints (NEW, do not touch /synthetic/*)
# -----------------------------
@app.get("/market/zero-gamma")
def market_zero_gamma(
    provider: str = Query("auto"),  # "auto" | "tradier" | "synthetic"
    symbol: str = Query("SPY"),
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    # synthetic knobs used when provider uses synthetic (or fallback)
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    seed: int = Query(42, ge=0, le=10_000),
    # zero-gamma params
    bracket_pct: float = Query(0.25, gt=0.02, le=0.80),
    dealer_sign: int = Query(-1),
    use_call_put_netting: bool = Query(True),
    mode: str = Query("netted"),  # "netted" | "raw"
    tol_rel: float = Query(1e-6, gt=0.0, lt=1e-1),
    max_iter: int = Query(140, ge=10, le=500),
):
    syn_cfg = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    synthetic_provider = SyntheticProvider(cfg=syn_cfg, seed=seed)

    tradier = _PROVIDER_SINGLETON.get("tradier")

    provider_norm = (provider or "auto").lower().strip()
    mode_norm = "raw" if (mode or "").lower() == "raw" else "netted"

    if provider_norm == "synthetic":
        pr = synthetic_provider.get_chain(symbol, expiry_days, spot_hint=spot)
    elif provider_norm == "tradier":
        if tradier is None:
            raise ValueError("Tradier provider not configured. Set TRADIER_TOKEN.")
        pr = tradier.get_chain(symbol, expiry_days, spot_hint=None)
    else:
        # auto
        if tradier is None:
            pr = synthetic_provider.get_chain(symbol, expiry_days, spot_hint=spot)
        else:
            auto = FallbackProvider(primary=tradier, fallback=synthetic_provider)
            pr = auto.get_chain(symbol, expiry_days, spot_hint=spot)

    chain = pr.chain
    cfg = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=use_call_put_netting)

    lo = float(chain.underlying.spot) * (1.0 - bracket_pct)
    hi = float(chain.underlying.spot) * (1.0 + bracket_pct)

    res = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode=mode_norm, tol_rel=tol_rel, max_iter=max_iter)

    return {
        "provider": provider_norm,
        "resolved_source": pr.source,
        "symbol": symbol,
        "spot": float(chain.underlying.spot),
        "expiry_days": int(expiry_days),
        "bracket": [lo, hi],
        "dealer_sign": dealer_sign,
        "use_call_put_netting": use_call_put_netting,
        "mode": mode_norm,
        "tol_rel": float(tol_rel),
        "max_iter": int(max_iter),
        "result": res,
        "notes": {
            "synthetic_fallback": "If provider=auto, real provider is attempted first; synthetic is fallback.",
            "tradier_token": "TRADIER_TOKEN env var must be set to use Tradier.",
        },
    }


@app.get("/market/zero-gamma/compare")
def market_zero_gamma_compare(
    provider: str = Query("auto"),
    symbol: str = Query("SPY"),
    spot: float = Query(500.0, gt=0),
    expiry_days: int = Query(30, ge=7, le=365),
    # synthetic knobs
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    strikes_pct_range: float = Query(0.12, gt=0.02, le=0.60),
    strikes_count: int = Query(41, ge=11, le=401),
    skew: float = Query(0.35, ge=0.0, le=5.0),
    smile: float = Query(0.15, ge=0.0, le=5.0),
    oi_base: int = Query(12000, ge=0, le=2_000_000),
    oi_width: float = Query(0.12, gt=0.01, le=2.0),
    tilt: float = Query(2.0, ge=0.0, le=20.0),
    min_share: float = Query(0.10, ge=0.0, le=0.49),
    seed: int = Query(42, ge=0, le=10_000),
    # compare params
    bracket_pct: float = Query(0.25, gt=0.02, le=0.80),
    dealer_sign: int = Query(-1),
    tol_rel: float = Query(1e-6, gt=0.0, lt=1e-1),
    max_iter: int = Query(140, ge=10, le=500),
):
    syn_cfg = _make_synth_cfg(
        spot=spot,
        expiry_days=expiry_days,
        base_iv=base_iv,
        strikes_pct_range=strikes_pct_range,
        strikes_count=strikes_count,
        skew=skew,
        smile=smile,
        oi_base=oi_base,
        oi_width=oi_width,
        tilt=tilt,
        min_share=min_share,
    )
    synthetic_provider = SyntheticProvider(cfg=syn_cfg, seed=seed)
    tradier = _PROVIDER_SINGLETON.get("tradier")

    provider_norm = (provider or "auto").lower().strip()

    if provider_norm == "synthetic":
        pr = synthetic_provider.get_chain(symbol, expiry_days, spot_hint=spot)
    elif provider_norm == "tradier":
        if tradier is None:
            raise ValueError("Tradier provider not configured. Set TRADIER_TOKEN.")
        pr = tradier.get_chain(symbol, expiry_days, spot_hint=None)
    else:
        if tradier is None:
            pr = synthetic_provider.get_chain(symbol, expiry_days, spot_hint=spot)
        else:
            auto = FallbackProvider(primary=tradier, fallback=synthetic_provider)
            pr = auto.get_chain(symbol, expiry_days, spot_hint=spot)

    chain = pr.chain
    cfg = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=True)

    lo = float(chain.underlying.spot) * (1.0 - bracket_pct)
    hi = float(chain.underlying.spot) * (1.0 + bracket_pct)

    netted = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="netted", tol_rel=tol_rel, max_iter=max_iter)
    raw = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="raw", tol_rel=tol_rel, max_iter=max_iter)

    both_found = bool(netted.get("found") and raw.get("found"))
    level_diff = (float(netted["level"]) - float(raw["level"])) if both_found else None

    return {
        "provider": provider_norm,
        "resolved_source": pr.source,
        "symbol": symbol,
        "spot": float(chain.underlying.spot),
        "expiry_days": int(expiry_days),
        "bracket": [lo, hi],
        "dealer_sign": dealer_sign,
        "tol_rel": float(tol_rel),
        "max_iter": int(max_iter),
        "netted": {"mode": "netted", "use_call_put_netting": True, "result": netted},
        "raw": {"mode": "raw", "use_call_put_netting": True, "result": raw},
        "delta": {"both_found": both_found, "level_diff": level_diff},
    }