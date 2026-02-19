# packages/core/math/black_scholes.py
from __future__ import annotations
import math

SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _d1(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    return (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def gamma_bs(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> float:
    """
    Black-Scholes gamma for European options (call/put share same gamma).
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma, q)
    return _norm_pdf(d1) * math.exp(-q * T) / (S * sigma * math.sqrt(T))