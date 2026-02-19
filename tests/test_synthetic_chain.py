from packages.core.data.synthetic import SyntheticConfig, generate_option_chain

def test_chain_integrity():
    cfg = SyntheticConfig(symbol="SPY", spot=500, expiry_days=30)
    chain = generate_option_chain(cfg, seed=42)

    assert chain.underlying.symbol == "SPY"
    assert chain.underlying.spot > 0
    assert len(chain.contracts) > 0

    # ensure both calls and puts exist
    rights = {c.right for c in chain.contracts}
    assert "C" in rights and "P" in rights

    # ensure no negative OI
    assert all(c.oi >= 0 for c in chain.contracts)