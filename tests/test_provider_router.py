# tests/test_provider_router.py
from packages.core.data.providers.router import FallbackProvider
from packages.core.data.providers.base import ProviderResult
from packages.core.schemas.market import UnderlyingSnapshot, OptionChainSnapshot

class Boom:
    def get_chain(self, symbol, expiry_days, *, spot_hint=None):
        raise RuntimeError("boom")

class Ok:
    def get_chain(self, symbol, expiry_days, *, spot_hint=None):
        chain = OptionChainSnapshot(
            underlying=UnderlyingSnapshot(symbol=symbol, spot=123.0, ts=None),
            contracts=[]
        )
        return ProviderResult(chain=chain, source="synthetic")

def test_fallback_provider_uses_fallback_on_error():
    p = FallbackProvider(primary=Boom(), fallback=Ok())
    res = p.get_chain("SPY", 30)
    assert res.source == "synthetic"
    assert float(res.chain.underlying.spot) == 123.0