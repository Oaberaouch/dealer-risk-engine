from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Literal
from datetime import datetime


class UnderlyingSnapshot(BaseModel):
    symbol: str = Field(..., examples=["SPY"])
    spot: float = Field(..., gt=0)
    ts: datetime


class OptionContract(BaseModel):
    symbol: str = Field(..., examples=["SPY"])
    expiry_days: int = Field(..., ge=1, le=365)
    strike: float = Field(..., gt=0)
    right: Literal["C", "P"]
    iv: float = Field(..., gt=0, le=5.0)  # 0%..500% (just safety bounds)
    oi: int = Field(..., ge=0)


class OptionChainSnapshot(BaseModel):
    underlying: UnderlyingSnapshot
    contracts: List[OptionContract]