# packages/core/schemas/market.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Literal, Dict, Any


OptionRight = Literal["C", "P"]


def _norm_right(x: str) -> OptionRight:
    r = (x or "").strip().upper()
    if r in ("C", "CALL"):
        return "C"
    if r in ("P", "PUT"):
        return "P"
    raise ValueError(f"Invalid option right: {x!r} (expected 'C' or 'P')")


@dataclass(frozen=True)
class UnderlyingSnapshot:
    symbol: str
    spot: float
    ts: datetime

    def __post_init__(self) -> None:
        if not self.symbol or not str(self.symbol).strip():
            raise ValueError("UnderlyingSnapshot.symbol is required")
        if self.spot <= 0:
            raise ValueError("UnderlyingSnapshot.spot must be > 0")
        if not isinstance(self.ts, datetime):
            raise ValueError("UnderlyingSnapshot.ts must be a datetime")


@dataclass(frozen=True)
class OptionContract:
    """
    Single option contract snapshot.
    - expiry_days: integer DTE used by your synthetic setup. Real providers can map DTE into this.
    - iv: implied vol as decimal (0.18 = 18%).
    - oi: open interest as integer contracts.
    """
    symbol: str
    expiry_days: int
    strike: float
    right: OptionRight
    iv: float
    oi: int

    # optional fields for future real providers (kept optional to not break your code now)
    expiry: Optional[datetime] = None  # actual expiry date/time if you have it
    volume: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None

    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.symbol or not str(self.symbol).strip():
            raise ValueError("OptionContract.symbol is required")
        if self.expiry_days <= 0:
            raise ValueError("OptionContract.expiry_days must be > 0")
        if self.strike <= 0:
            raise ValueError("OptionContract.strike must be > 0")
        # normalize right
        object.__setattr__(self, "right", _norm_right(self.right))  # type: ignore[arg-type]
        if self.iv <= 0:
            raise ValueError("OptionContract.iv must be > 0")
        if self.oi < 0:
            raise ValueError("OptionContract.oi must be >= 0")
        if self.volume is not None and self.volume < 0:
            raise ValueError("OptionContract.volume must be >= 0")
        for px_name in ("bid", "ask", "last"):
            px = getattr(self, px_name)
            if px is not None and px < 0:
                raise ValueError(f"OptionContract.{px_name} must be >= 0")


@dataclass(frozen=True)
class OptionChainSnapshot:
    """
    Snapshot of the whole chain at a timestamp.
    """
    underlying: UnderlyingSnapshot
    contracts: List[OptionContract]

    # optional: provider and any raw meta
    source: str = "synthetic"
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.underlying is None:
            raise ValueError("OptionChainSnapshot.underlying is required")
        if self.contracts is None:
            raise ValueError("OptionChainSnapshot.contracts is required")

        # basic integrity checks
        sym = self.underlying.symbol
        for c in self.contracts:
            if c.symbol != sym:
                raise ValueError(f"Contract symbol {c.symbol} != underlying symbol {sym}")
            if c.strike <= 0:
                raise ValueError("All strikes must be > 0")
            if c.expiry_days <= 0:
                raise ValueError("All expiry_days must be > 0")

    @property
    def timestamp(self) -> str:
        # convenience for API responses
        return self.underlying.ts.isoformat()

    def strikes(self) -> List[float]:
        return sorted({float(c.strike) for c in self.contracts})

    def expiries_days(self) -> List[int]:
        return sorted({int(c.expiry_days) for c in self.contracts})