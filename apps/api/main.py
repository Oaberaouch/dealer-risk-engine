# apps/api/main.py
from __future__ import annotations

from fastapi import FastAPI, Query

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.models.gex import (
    GexConfig,
    gex_by_strike,
    total_gex,
    gamma_profile,
    gamma_profile_both,
    zero_gamma_level,
)

app = FastAPI(title="SU-57 (Synthetic SPY) API", version="0.3.1")


@app.get("/health")
def health():
    return {"status": "ok"}


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
    res = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode=mode)

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "bracket": [lo, hi],
        "dealer_sign": dealer_sign,
        "use_call_put_netting": use_call_put_netting,
        "mode": mode,
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

    netted = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="netted")
    raw = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="raw")

    both_found = bool(netted["found"] and raw["found"])
    level_diff = (float(netted["level"]) - float(raw["level"])) if both_found else None

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "bracket": [lo, hi],
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


# ////////////////////////////////////////////////////////////////////

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
    scale: str = Query("raw"),  # "raw" | "k" | "m" | "b"
    seed: int = Query(42, ge=0, le=10_000),
):
    """
    Single "sanity" endpoint:
    - zero-gamma (netted vs raw)
    - sign at spot (netted vs raw)
    - max/min over a span for both
    - most influential strike by |net OI| (calls - puts)
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

    def _scale_factor(name: str) -> float:
        n = (name or "raw").strip().lower()
        if n in ("raw", "none", "1"):
            return 1.0
        if n in ("k", "thousand", "thousands"):
            return 1e3
        if n in ("m", "mm", "million", "millions"):
            return 1e6
        if n in ("b", "bn", "billion", "billions"):
            return 1e9
        return 1.0

    sf = _scale_factor(scale)
    scale_label = (scale or "raw").strip().lower()
    if scale_label in ("none", "1"):
        scale_label = "raw"

    def _fmt(x: float) -> float:
        return float(x) / sf

    lo = spot * (1.0 - bracket_pct)
    hi = spot * (1.0 + bracket_pct)

    # Use the same assumption you’ve been testing:
    # we compute both "netted" (aggregate by strike, calls +, puts -)
    # and "raw" (per-contract signed OI, still calls +, puts -; different route)
    cfg_netted = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=True)
    cfg_raw = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=True)

    zg_netted = zero_gamma_level(chain, cfg_netted, bracket=(lo, hi), mode="netted")
    zg_raw = zero_gamma_level(chain, cfg_raw, bracket=(lo, hi), mode="raw")

    # Scale gex endpoints for readability (keep level unchanged)
    for d in (zg_netted, zg_raw):
        if isinstance(d, dict):
            if "gex_lo" in d and d["gex_lo"] is not None:
                d["gex_lo"] = _fmt(float(d["gex_lo"]))
            if "gex_hi" in d and d["gex_hi"] is not None:
                d["gex_hi"] = _fmt(float(d["gex_hi"]))

    # profiles via the existing compare function (safest / consistent)
    s_min = spot * (1.0 - span_pct)
    s_max = spot * (1.0 + span_pct)

    prof = gamma_profile_both(chain, cfg_netted, s_min=s_min, s_max=s_max, steps=steps)
    grid = prof["S"]
    gex_netted = prof["netted"]
    gex_raw = prof["raw"]

    def _sign(x: float) -> str:
        if x > 0:
            return "positive"
        if x < 0:
            return "negative"
        return "zero"

    # extrema
    import numpy as np

    net_max = max(gex_netted)
    net_min = min(gex_netted)
    raw_max = max(gex_raw)
    raw_min = min(gex_raw)

    net_max_S = float(grid[int(np.argmax(gex_netted))])
    net_min_S = float(grid[int(np.argmin(gex_netted))])
    raw_max_S = float(grid[int(np.argmax(gex_raw))])
    raw_min_S = float(grid[int(np.argmin(gex_raw))])

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

    # at spot: use nearest grid point from prof (stable + consistent)
    nearest_idx = int(np.argmin([abs(float(S) - float(spot)) for S in grid]))
    nearest_S = float(grid[nearest_idx])

    g_spot_netted = float(gex_netted[nearest_idx])
    g_spot_raw = float(gex_raw[nearest_idx])

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "dealer_sign": dealer_sign,
        "scale": scale_label,
        "scale_divisor": sf,  # values shown are divided by this
        "bracket": [lo, hi],
        "range": [s_min, s_max],
        "steps": steps,
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
            "netted": {"mode": "netted", "result": zg_netted},
            "raw": {"mode": "raw", "result": zg_raw},
        },
        "at_spot": {
            "note": "at_spot uses the nearest S grid point from gamma_profile_both",
            "nearest_S": nearest_S,
            "netted": {"gex": _fmt(g_spot_netted), "sign": _sign(g_spot_netted)},
            "raw": {"gex": _fmt(g_spot_raw), "sign": _sign(g_spot_raw)},
        },
        "extrema_over_span": {
            "netted": {"max": _fmt(net_max), "max_S": net_max_S, "min": _fmt(net_min), "min_S": net_min_S},
            "raw": {"max": _fmt(raw_max), "max_S": raw_max_S, "min": _fmt(raw_min), "min_S": raw_min_S},
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