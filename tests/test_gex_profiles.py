import math

from packages.core.data.synthetic import SyntheticConfig, generate_option_chain
from packages.core.models.gex import GexConfig, gamma_profile_both


def test_gamma_profile_both_shapes_and_closeness():
    cfg_syn = SyntheticConfig(
        symbol="SPY",
        spot=500.0,
        expiry_days=30,
        strikes_pct_range=0.12,
        strikes_count=41,
        base_iv=0.18,
        skew=0.35,
        smile=0.15,
        oi_base=20000,
        oi_width=0.10,
        tilt=3.0,
        min_share=0.10,
    )
    chain = generate_option_chain(cfg_syn, seed=42)

    cfg = GexConfig(dealer_sign=-1, use_call_put_netting=True)

    s_min, s_max, steps = 300.0, 700.0, 121
    prof = gamma_profile_both(chain, cfg, s_min=s_min, s_max=s_max, steps=steps)

    S = prof["S"]
    netted = prof["netted"]
    raw = prof["raw"]

    assert len(S) == steps
    assert len(netted) == steps
    assert len(raw) == steps

    # Ensure grid endpoints match
    assert math.isclose(S[0], s_min, rel_tol=0, abs_tol=1e-9)
    assert math.isclose(S[-1], s_max, rel_tol=0, abs_tol=1e-9)

    # Closeness check (regression guard). Tune threshold if needed.
    max_abs_raw = max(abs(x) for x in raw) or 1.0
    max_abs_diff = max(abs(a - b) for a, b in zip(netted, raw))
    rel = max_abs_diff / max_abs_raw

    # With current implementation, netted vs raw should be close for canonical params.
    assert rel < 0.10  # 10% guardrail (tighten later if you want)