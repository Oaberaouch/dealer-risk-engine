from packages.core.math.black_scholes import gamma_bs

def test_gamma_positive_basic():
    g = gamma_bs(S=100, K=100, T=30/365, r=0.05, sigma=0.2, q=0.0)
    assert g > 0

def test_gamma_zero_invalid_inputs():
    assert gamma_bs(S=0, K=100, T=30/365, r=0.05, sigma=0.2) == 0.0
    assert gamma_bs(S=100, K=0, T=30/365, r=0.05, sigma=0.2) == 0.0
    assert gamma_bs(S=100, K=100, T=0, r=0.05, sigma=0.2) == 0.0
    assert gamma_bs(S=100, K=100, T=30/365, r=0.05, sigma=0.0) == 0.0