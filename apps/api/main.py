from fastapi import FastAPI, Query
from packages.core.models.synthetic import SyntheticConfig, generate_underlying_path, generate_option_chain
from packages.core.models.vol_metrics import realized_vol_annualized, atm_iv, variance_risk_premium

app = FastAPI(title="Dealer Risk Engine", version="0.0.2")

@app.get("/health")
def health():
    return {"status": "ok", "service": "dealer-risk-engine"}

@app.get("/synthetic/vol")
def synthetic_vol(
    spot: float = Query(500.0, gt=0),
    days: int = Query(30, ge=10, le=252),
    expiry_days: int = Query(30, ge=7, le=365),
    base_iv: float = Query(0.18, gt=0.01, le=2.0),
    daily_sigma: float = Query(0.012, gt=0.001, le=0.1),
    seed: int = Query(42, ge=0, le=10_000),
):
    cfg = SyntheticConfig(
        symbol="SPY",
        spot=spot,
        days=days,
        expiry_days=expiry_days,
        base_iv=base_iv,
        daily_sigma=daily_sigma,
    )

    prices = generate_underlying_path(cfg, seed=seed)
    chain = generate_option_chain(cfg, seed=seed)

    rv = realized_vol_annualized(prices)
    iv = atm_iv(chain)
    vrp = variance_risk_premium(iv, rv)

    return {
        "symbol": "SPY",
        "spot": spot,
        "rv_annualized": rv,
        "iv_atm": iv,
        "vrp": vrp,
        "notes": {
            "rv": "Annualized realized volatility from synthetic log returns",
            "iv": "ATM proxy from synthetic option chain",
            "vrp": "IV - RV; negative implies fragility (moving more than priced)",
        },
    }