# apps/api/main.py
from __future__ import annotations

import os
from typing import Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query

# Load .env (POLYGON_API_KEY, etc.) as early as possible (but after __future__)
load_dotenv()

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.models.gex import (
    GexConfig,
    gex_by_strike,
    total_gex,
    gamma_profile,
    gamma_profile_both,
    zero_gamma_level,
)
from packages.core.data.providers.polygon import PolygonProvider, PolygonError

app = FastAPI(title="SU-57 Dealer Risk Engine", version="0.5.0")


# -----------------------------
# Root / health
# -----------------------------
@app.get("/")
def root():
    return {"name": "SU-57 Dealer Risk Engine", "status": "ok", "docs": "/docs", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "ok"}


# -----------------------------
# Real data helpers (Polygon)
# -----------------------------
def _polygon() -> PolygonProvider:
    try:
        return PolygonProvider.from_env()
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"POLYGON_API_KEY missing or invalid. Put it in .env and restart. ({e})",
        )


def _best_effort_spot(symbol: str) -> Dict[str, Any]:
    """
    Best-effort spot resolver for free plans:
    - Try Polygon last trade (may 403 on free)
    - Fall back to prev close if your PolygonProvider supports it in main.py logic
      (we implement fallback here using Polygon endpoints directly).
    """
    symbol = symbol.upper().strip()
    p = _polygon()

    # 1) Try provider.get_spot() (your polygon.py currently hits /v2/last/trade/{ticker})
    try:
        u = p.get_spot(symbol)
        return {"symbol": symbol, "provider": "polygon", "source": "last_trade", "spot": float(u.spot), "ts": u.ts.isoformat()}
    except PolygonError as e:
        msg = str(e)

        # If it’s NOT_AUTHORIZED / 403, fall back to prev close
        if "HTTP 403" not in msg and "NOT_AUTHORIZED" not in msg:
            # other Polygon errors should surface
            raise HTTPException(status_code=502, detail=f"Polygon spot fetch failed: {e}")

    # 2) Fallback: previous close
    # Polygon endpoint: GET /v2/aggs/ticker/{ticker}/prev?adjusted=true&apiKey=...
    import httpx
    from datetime import datetime, timezone

    url = f"{p.base_url}/v2/aggs/ticker/{symbol}/prev"
    try:
        with httpx.Client(timeout=p.timeout_s) as client:
            r = client.get(url, params={"adjusted": "true", "apiKey": p.api_key})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Polygon prev_close request failed: {e}")

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Polygon prev_close HTTP {r.status_code}: {r.text}")

    data = r.json()
    results = (data.get("results") or [])
    if not results:
        raise HTTPException(status_code=502, detail=f"Polygon prev_close missing results. Payload={data}")

    row = results[0]
    close_px = row.get("c")
    ts_ms = row.get("t")
    if close_px is None:
        raise HTTPException(status_code=502, detail=f"Polygon prev_close missing close price. Payload={data}")

    if ts_ms is None:
        ts = datetime.now(timezone.utc)
    else:
        ts = datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc)

    return {"symbol": symbol, "provider": "polygon", "source": "prev_close", "spot": float(close_px), "ts": ts.isoformat()}


# -----------------------------
# Real-data endpoint: spot
# -----------------------------
@app.get("/market/spot")
def market_spot(symbol: str = Query("SPY", min_length=1)):
    """
    Real-data spot resolver. On Polygon free plans, may fall back to prev_close.
    """
    return _best_effort_spot(symbol)


# -----------------------------
# Synthetic config builder
# -----------------------------
def _make_synth_cfg(
    symbol: str,
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
        symbol=symbol,
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


# -----------------------------
# NEW: Hybrid endpoints (real spot + synthetic chain)
# -----------------------------
@app.get("/market/synthetic-chain")
def market_synthetic_chain(
    symbol: str = Query("SPY", min_length=1),
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
    """
    Hybrid: fetch real spot (best-effort, prev_close if needed) + generate synthetic options chain around it.
    """
    spot_payload = _best_effort_spot(symbol)
    spot = float(spot_payload["spot"])
    sym = spot_payload["symbol"]

    cfg = _make_synth_cfg(
        symbol=sym,
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
        "symbol": sym,
        "spot": spot,
        "spot_meta": spot_payload,
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
            {"strike": c.strike, "right": c.right, "expiry_days": c.expiry_days, "iv": c.iv, "oi": c.oi}
            for c in chain.contracts
        ],
    }


@app.get("/market/zero-gamma")
def market_zero_gamma(
    symbol: str = Query("SPY", min_length=1),
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
    dealer_sign: int = Query(-1),
    use_call_put_netting: bool = Query(True),
    mode: str = Query("netted"),  # "netted" or "raw"
    tol_rel: float = Query(1e-6, gt=0.0, le=1e-2),
    max_iter: int = Query(140, ge=20, le=500),
    seed: int = Query(42, ge=0, le=10_000),
):
    """
    Hybrid: real spot (best effort) + synthetic chain + zero-gamma solve.
    This lets you validate the full pipeline before real options-chain integration.
    """
    spot_payload = _best_effort_spot(symbol)
    spot = float(spot_payload["spot"])
    sym = spot_payload["symbol"]

    cfg_syn = _make_synth_cfg(
        symbol=sym,
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
        "symbol": sym,
        "spot": spot,
        "spot_meta": spot_payload,
        "expiry_days": expiry_days,
        "bracket": [lo, hi],
        "dealer_sign": dealer_sign,
        "use_call_put_netting": use_call_put_netting,
        "mode": mode,
        "tol_rel": tol_rel,
        "max_iter": max_iter,
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


# -----------------------------
# Synthetic endpoints (UNCHANGED behavior)
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
            {"strike": c.strike, "right": c.right, "expiry_days": c.expiry_days, "iv": c.iv, "oi": c.oi}
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
    tol_rel: float = Query(1e-6, gt=0.0, le=1e-2),
    max_iter: int = Query(140, ge=20, le=500),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
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
        "tol_rel": tol_rel,
        "max_iter": max_iter,
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
    tol_rel: float = Query(1e-6, gt=0.0, le=1e-2),
    max_iter: int = Query(140, ge=20, le=500),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
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
    chain = generate_option_chain(cfg_syn, seed=seed)

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
        "tol_rel": tol_rel,
        "max_iter": max_iter,
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
    span_pct: float = Query(0.40, gt=0.02, le=0.80),
    steps: int = Query(121, ge=31, le=401),
    dealer_sign: int = Query(-1),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg_syn = _make_synth_cfg(
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
    chain = generate_option_chain(cfg_syn, seed=seed)

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