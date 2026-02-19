# tests/test_zero_gamma.py
from __future__ import annotations

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.models.gex import (
    GexConfig,
    zero_gamma_level,
    total_gex_at_spot_netted,
    total_gex_at_spot_raw,
)


def _make_chain():
    cfg = SyntheticConfig(
        symbol="SPY",
        spot=500.0,
        expiry_days=30,
        base_iv=0.18,
        strikes_pct_range=0.12,
        strikes_count=41,
        skew=0.35,
        smile=0.15,
        oi_base=20000,
        oi_width=0.10,
        tilt=3.0,
        min_share=0.10,
    )
    return generate_option_chain(cfg, seed=42)


def _same_sign(a: float, b: float) -> bool:
    return (a >= 0 and b >= 0) or (a <= 0 and b <= 0)


def test_zero_gamma_returns_endpoint_evals_netted():
    chain = _make_chain()
    cfg = GexConfig(dealer_sign=-1, use_call_put_netting=True)

    lo, hi = 300.0, 700.0
    res = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="netted")

    assert "gex_lo" in res and "gex_hi" in res
    # Must actually be f(lo) and f(hi)
    assert float(res["gex_lo"]) == float(total_gex_at_spot_netted(chain, cfg, lo))
    assert float(res["gex_hi"]) == float(total_gex_at_spot_netted(chain, cfg, hi))


def test_zero_gamma_returns_endpoint_evals_raw():
    chain = _make_chain()
    cfg = GexConfig(dealer_sign=-1, use_call_put_netting=True)

    lo, hi = 300.0, 700.0
    res = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode="raw")

    assert "gex_lo" in res and "gex_hi" in res
    assert float(res["gex_lo"]) == float(total_gex_at_spot_raw(chain, cfg, lo))
    assert float(res["gex_hi"]) == float(total_gex_at_spot_raw(chain, cfg, hi))


def test_zero_gamma_strong_guarantee_when_found_netted():
    chain = _make_chain()
    cfg = GexConfig(dealer_sign=-1, use_call_put_netting=True)

    res = zero_gamma_level(chain, cfg, bracket=(300.0, 700.0), mode="netted", tol_rel=1e-6, max_iter=140)

    # Either: no sign change => found False w/ reason
    # Or: found True => must satisfy abs(f(level)) <= target.
    if not res["found"]:
        assert res["reason"] in ("no_sign_change", "max_iter")
        if res["reason"] == "no_sign_change":
            assert _same_sign(float(res["gex_lo"]), float(res["gex_hi"]))
        return

    level = float(res["level"])
    f_level = float(total_gex_at_spot_netted(chain, cfg, level))
    assert abs(f_level) <= float(res["target"])


def test_zero_gamma_strong_guarantee_when_found_raw():
    chain = _make_chain()
    cfg = GexConfig(dealer_sign=-1, use_call_put_netting=True)

    res = zero_gamma_level(chain, cfg, bracket=(300.0, 700.0), mode="raw", tol_rel=1e-6, max_iter=140)

    if not res["found"]:
        assert res["reason"] in ("no_sign_change", "max_iter")
        if res["reason"] == "no_sign_change":
            assert _same_sign(float(res["gex_lo"]), float(res["gex_hi"]))
        return

    level = float(res["level"])
    f_level = float(total_gex_at_spot_raw(chain, cfg, level))
    assert abs(f_level) <= float(res["target"])


def test_zero_gamma_includes_solver_diagnostics():
    chain = _make_chain()
    cfg = GexConfig(dealer_sign=-1, use_call_put_netting=True)

    res = zero_gamma_level(chain, cfg, bracket=(300.0, 700.0), mode="netted")
    for k in ("found", "mode", "iters", "scale", "target", "bracket_final", "reason", "converged"):
        assert k in res