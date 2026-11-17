"""Strategy contract: a pure ``decide(view, params) -> Decision`` plus a versioned registry."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Callable, Literal

from .view import PointInTimeView

Direction = Literal["long", "short", "exit", "hold"]
DIRECTIONS: tuple[Direction, ...] = ("long", "short", "exit", "hold")


@dataclass(frozen=True)
class Signal:
    """What a strategy function returns; ``run_decision`` wraps it into a Decision."""
    direction: Direction
    strength: float = 0.0  # [0, 1]; a ranking strength, NOT a probability
    reasons: tuple[str, ...] = ()
    features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.direction not in DIRECTIONS:
            raise ValueError(f"invalid direction {self.direction!r}")
        if not (0.0 <= self.strength <= 1.0) or math.isnan(self.strength):
            raise ValueError(f"strength must be in [0, 1], got {self.strength}")
        for k, val in self.features.items():
            if not math.isfinite(val):
                raise ValueError(f"feature {k} is not finite: {val}")


@dataclass(frozen=True)
class Decision:
    strategy: str  # "name@version"
    symbol: str
    asof: dt.date
    direction: Direction
    strength: float
    reasons: tuple[str, ...]
    features: dict[str, float]
    bars_used: int


StrategyFn = Callable[[PointInTimeView, dict], Signal]


@dataclass(frozen=True)
class StrategySpec:
    name: str
    version: str
    min_bars: int
    params: dict
    fn: StrategyFn
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"


class UnknownStrategy(KeyError):
    pass


_REGISTRY: dict[str, StrategySpec] = {}


def register(spec: StrategySpec) -> StrategySpec:
    if spec.key in _REGISTRY:
        raise ValueError(f"strategy {spec.key} already registered")
    _REGISTRY[spec.key] = spec
    return spec


def get_spec(key: str) -> StrategySpec:
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownStrategy(f"unknown strategy version {key!r}; known: {sorted(_REGISTRY)}") from None


def all_specs() -> list[StrategySpec]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
