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
    tol_rel: float = Query(1e-6, gt=0.0, le=1e-2),  # NEW (default preserves behavior)
    max_iter: int = Query(140, ge=20, le=500),      # optional, keeps solver robust
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
    res = zero_gamma_level(
        chain,
        cfg,
        bracket=(lo, hi),
        mode=mode,
        tol_rel=float(tol_rel),
        max_iter=int(max_iter),
    )

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
    tol_rel: float = Query(1e-6, gt=0.0, le=1e-2),  # NEW
    max_iter: int = Query(140, ge=20, le=500),      # optional
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

    netted = zero_gamma_level(
        chain,
        cfg,
        bracket=(lo, hi),
        mode="netted",
        tol_rel=float(tol_rel),
        max_iter=int(max_iter),
    )
    raw = zero_gamma_level(
        chain,
        cfg,
        bracket=(lo, hi),
        mode="raw",
        tol_rel=float(tol_rel),
        max_iter=int(max_iter),
    )

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
    scale: str = Query("raw"),  # "raw" | "k" | "m" | "b"
    seed: int = Query(42, ge=0, le=10_000),
):
    """
    Single "sanity" endpoint:
    - zero-gamma (netted vs raw)
    - sign at spot (netted vs raw)
    - max/min over a span for both
    - most influential strike by |net OI| (calls - puts)
    - optional scaling of GEX numbers for readability
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

    # scaling
    scale_key = (scale or "raw").lower().strip()
    scale_divisor = 1.0
    if scale_key in ("k", "thousand"):
        scale_divisor = 1e3
        scale_key = "k"
    elif scale_key in ("m", "million"):
        scale_divisor = 1e6
        scale_key = "m"
    elif scale_key in ("b", "billion"):
        scale_divisor = 1e9
        scale_key = "b"
    else:
        scale_key = "raw"
        scale_divisor = 1.0

    def _sc(x: float) -> float:
        return float(x) / float(scale_divisor)

    lo = spot * (1.0 - bracket_pct)
    hi = spot * (1.0 + bracket_pct)

    cfg_eval = GexConfig(dealer_sign=dealer_sign, use_call_put_netting=True)

    zg_netted = zero_gamma_level(chain, cfg_eval, bracket=(lo, hi), mode="netted")
    zg_raw = zero_gamma_level(chain, cfg_eval, bracket=(lo, hi), mode="raw")

    # profiles (use your existing compare profile builder)
    s_min = spot * (1.0 - span_pct)
    s_max = spot * (1.0 + span_pct)

    prof = gamma_profile_both(chain, cfg_eval, s_min=s_min, s_max=s_max, steps=steps)

    # at spot: use nearest grid point from profile for consistency
    S_grid = prof["S"]
    nearest_S = min(S_grid, key=lambda x: abs(float(x) - float(spot))) if S_grid else float(spot)
    idx = S_grid.index(nearest_S) if S_grid else 0

    g_spot_netted = float(prof["netted"][idx]) if prof["netted"] else 0.0
    g_spot_raw = float(prof["raw"][idx]) if prof["raw"] else 0.0

    def _sign(x: float) -> str:
        if x > 0:
            return "positive"
        if x < 0:
            return "negative"
        return "zero"

    # extrema over span
    netted_vals = [float(x) for x in prof["netted"]]
    raw_vals = [float(x) for x in prof["raw"]]
    net_max = max(netted_vals) if netted_vals else 0.0
    net_min = min(netted_vals) if netted_vals else 0.0
    raw_max = max(raw_vals) if raw_vals else 0.0
    raw_min = min(raw_vals) if raw_vals else 0.0

    net_max_S = float(S_grid[int(netted_vals.index(net_max))]) if netted_vals else float(spot)
    net_min_S = float(S_grid[int(netted_vals.index(net_min))]) if netted_vals else float(spot)
    raw_max_S = float(S_grid[int(raw_vals.index(raw_max))]) if raw_vals else float(spot)
    raw_min_S = float(S_grid[int(raw_vals.index(raw_min))]) if raw_vals else float(spot)

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

    # scale gex_lo/gex_hi in zero-gamma outputs for readability
    def _scale_zg(zg: dict) -> dict:
        if not isinstance(zg, dict):
            return zg
        out = dict(zg)
        if "gex_lo" in out and out["gex_lo"] is not None:
            out["gex_lo"] = _sc(float(out["gex_lo"]))
        if "gex_hi" in out and out["gex_hi"] is not None:
            out["gex_hi"] = _sc(float(out["gex_hi"]))
        if "gex_level" in out and out["gex_level"] is not None:
            out["gex_level"] = _sc(float(out["gex_level"]))
        if "target" in out and out["target"] is not None:
            out["target"] = _sc(float(out["target"]))
        return out

    return {
        "symbol": "SPY",
        "spot": spot,
        "expiry_days": expiry_days,
        "dealer_sign": dealer_sign,
        "scale": scale_key,
        "scale_divisor": float(scale_divisor),
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
            "netted": {"mode": "netted", "result": _scale_zg(zg_netted)},
            "raw": {"mode": "raw", "result": _scale_zg(zg_raw)},
        },
        "at_spot": {
            "note": "at_spot uses the nearest S grid point from gamma_profile_both",
            "nearest_S": float(nearest_S),
            "netted": {"gex": _sc(g_spot_netted), "sign": _sign(g_spot_netted)},
            "raw": {"gex": _sc(g_spot_raw), "sign": _sign(g_spot_raw)},
        },
        "extrema_over_span": {
            "netted": {
                "max": _sc(net_max),
                "max_S": net_max_S,
                "min": _sc(net_min),
                "min_S": net_min_S,
            },
            "raw": {
                "max": _sc(raw_max),
                "max_S": raw_max_S,
                "min": _sc(raw_min),
                "min_S": raw_min_S,
            },
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