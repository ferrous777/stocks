"""Pydantic schemas shared by the API, CLI and services."""

from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

SYMBOL_PATTERN = r"^\^?[A-Z0-9][A-Z0-9.=\-]{0,14}$"
GROUP_PATTERN = r"^[a-z0-9_]{1,40}$"


class AssetClass(str, Enum):
    equity = "equity"
    etf = "etf"
    mutual_fund = "mutual_fund"
    future = "future"
    index = "index"
    fx = "fx"


class FactorLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    relation: str = Field(min_length=1, max_length=40, description="e.g. 'driver', 'peer', 'hedge'")


class SymbolBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    asset_class: AssetClass
    sector: str | None = None
    groups: list[str] = Field(default_factory=list)
    factors: list[FactorLink] = Field(default_factory=list)
    tradable: bool = True
    enabled: bool = True
    priority: int = Field(default=1, ge=0, le=3)
    shortable: bool = False

    @field_validator("groups")
    @classmethod
    def _groups(cls, v: list[str]) -> list[str]:
        import re
        for g in v:
            if not re.fullmatch(GROUP_PATTERN, g):
                raise ValueError(f"invalid group slug {g!r}")
        return sorted(set(v))


class SymbolIn(SymbolBase):
    symbol: str = Field(pattern=SYMBOL_PATTERN)


class SymbolPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    asset_class: AssetClass | None = None
    sector: str | None = None
    groups: list[str] | None = None
    factors: list[FactorLink] | None = None
    tradable: bool | None = None
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=3)
    shortable: bool | None = None


class GroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    description: str | None = None


class BarOut(BaseModel):
    symbol: str
    interval: str
    session: dt.date
    ts: dt.datetime
    ts_end: dt.datetime
    o: float
    h: float
    l: float
    c: float
    v: float | None
    basis: str
