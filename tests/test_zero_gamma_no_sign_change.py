# tests/test_zero_gamma_no_sign_change.py
from __future__ import annotations

import math

import pytest

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.models.gex import (
    GexConfig,
    total_gex_at_spot_netted,
    total_gex_at_spot_raw,
    zero_gamma_level,
)
from packages.core.schemas.market import OptionChainSnapshot, OptionContract


def _make_chain_structural_no_cross(seed: int = 42) -> OptionChainSnapshot:
    """
    Build a chain that cannot cross zero under call/put netting by construction:
    - keep calls OI as-is
    - force puts OI = 0

    Since OptionContract is frozen, we rebuild the contracts list.
    """
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
    chain = generate_option_chain(cfg, seed=seed)

    new_contracts = []
    for c in chain.contracts:
        if str(c.right).upper() == "P":
            # recreate with oi=0 (keep everything else)
            new_contracts.append(
                OptionContract(
                    symbol=c.symbol,
                    expiry_days=int(c.expiry_days),
                    strike=float(c.strike),
                    right=str(c.right),
                    iv=float(c.iv),
                    oi=0,
                    expiry=getattr(c, "expiry", None),
                    volume=getattr(c, "volume", None),
                    bid=getattr(c, "bid", None),
                    ask=getattr(c, "ask", None),
                    last=getattr(c, "last", None),
                    meta=getattr(c, "meta", {}) or {},
                )
            )
        else:
            new_contracts.append(c)

    return OptionChainSnapshot(
        underlying=chain.underlying,
        contracts=new_contracts,
        source=getattr(chain, "source", "synthetic"),
        meta=getattr(chain, "meta", {}) or {},
    )


def _has_sign_change(f_lo: float, f_hi: float) -> bool:
    if f_lo == 0.0 or f_hi == 0.0:
        return True
    return (f_lo > 0.0 and f_hi < 0.0) or (f_lo < 0.0 and f_hi > 0.0)


@pytest.mark.parametrize("mode", ["netted", "raw"])
def test_zero_gamma_reports_not_found_when_no_sign_change(mode: str):
    chain = _make_chain_structural_no_cross()
    cfg = GexConfig(dealer_sign=-1, use_call_put_netting=True)

    spot = float(chain.underlying.spot)
    lo = spot * 0.60  # 300
    hi = spot * 1.40  # 700

    f = total_gex_at_spot_netted if mode == "netted" else total_gex_at_spot_raw

    f_lo = float(f(chain, cfg, lo))
    f_hi = float(f(chain, cfg, hi))

    # must be no sign change for this constructed chain
    assert not _has_sign_change(f_lo, f_hi)

    res = zero_gamma_level(chain, cfg, bracket=(lo, hi), mode=mode)

    assert res["found"] is False

    # diagnostics must be present
    for k in (
        "found",
        "mode",
        "iters",
        "target",
        "bracket_final",
        "reason",
        "converged",
        "gex_lo",
        "gex_hi",
    ):
        assert k in res

    # endpoint evals must match exactly
    assert math.isclose(float(res["gex_lo"]), f_lo, rel_tol=0.0, abs_tol=0.0)
    assert math.isclose(float(res["gex_hi"]), f_hi, rel_tol=0.0, abs_tol=0.0)

    assert str(res["reason"]).lower() in {"no_sign_change", "no sign change", "no-sign-change"}

    lo2, hi2 = res["bracket_final"]
    assert float(lo2) >= float(lo)
    assert float(hi2) <= float(hi)