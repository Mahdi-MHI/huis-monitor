"""Judge a neighbourhood against the limits in a criteria file."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from huis_monitor.stats import OTHER_CRIMES, SHARE_COLUMNS, NeighbourhoodStats

# Every figure that can be limited with ``min_<name>`` or ``max_<name>``.
METRICS: dict[str, Callable[[NeighbourhoodStats], float | None]] = {
    "residents": lambda s: s.residents,
    "origin_nl_pct": lambda s: s.origin_nl_pct,
    "origin_europe_pct": lambda s: s.origin_europe_pct,
    "origin_outside_europe_pct": lambda s: s.origin_outside_europe_pct,
    "density_per_km2": lambda s: s.density_per_km2,
    "avg_woz_eur": lambda s: s.avg_woz_eur,
    "owner_occupied_pct": lambda s: s.owner_occupied_pct,
    "avg_income_eur": lambda s: s.avg_income_eur,
    "lowest40_income_households_pct": lambda s: s.lowest40_income_households_pct,
    "urbanity": lambda s: s.urbanity,
    "crimes_total_per_1000": lambda s: s.per_1000(s.crimes_total),
    "burglaries_per_1000": lambda s: s.per_1000(s.burglaries),
    "violent_crimes_per_1000": lambda s: s.per_1000(s.violent_crimes),
    "vandalism_per_1000": lambda s: s.per_1000(s.vandalism),
    "bike_thefts_per_1000": lambda s: s.per_1000(s.bike_thefts),
}


def _share(name: str) -> Callable[[NeighbourhoodStats], float | None]:
    return lambda s: s.shares.get(name)


def _other_crime(name: str) -> Callable[[NeighbourhoodStats], float | None]:
    return lambda s: s.per_1000(s.other_crimes.get(name))


METRICS.update({name: _share(name) for name in SHARE_COLUMNS})
METRICS.update({f"{name}_per_1000": _other_crime(name) for name in OTHER_CRIMES})


class CriteriaError(Exception):
    """Raised when the criteria file is missing or contains a mistake."""


@dataclass(frozen=True)
class Limit:
    """One line of the criteria file, such as ``max_burglaries_per_1000 = 3``."""

    metric: str
    kind: str  # "min" or "max"
    value: float


@dataclass(frozen=True)
class Verdict:
    """Outcome for one neighbourhood.

    ``failures`` maps each figure that breaks its limit to the reason.
    ``missing`` lists the limited figures for which CBS publishes no value.
    """

    failures: dict[str, str]
    missing: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        """Every limit was checked and met."""
        return not self.failures and not self.missing

    @property
    def unknown(self) -> bool:
        """No limit is broken, but some figures could not be checked."""
        return not self.failures and bool(self.missing)


def load_limits(path: Path) -> list[Limit]:
    """Read the ``[limits]`` table of a TOML criteria file."""
    try:
        with path.open("rb") as file:
            table = tomllib.load(file).get("limits", {})
    except FileNotFoundError as exc:
        raise CriteriaError(f"Criteria file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CriteriaError(f"Criteria file {path} is not valid TOML: {exc}") from exc

    limits = []
    for key, value in table.items():
        kind, _, metric = key.partition("_")
        if kind not in ("min", "max") or metric not in METRICS:
            known = ", ".join(sorted(METRICS))
            raise CriteriaError(
                f"Unknown limit {key!r}. Use min_ or max_ followed by one of: {known}"
            )
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise CriteriaError(f"Limit {key!r} must be a number, not {value!r}")
        limits.append(Limit(metric=metric, kind=kind, value=float(value)))
    return limits


def evaluate(stats: NeighbourhoodStats, limits: list[Limit]) -> Verdict:
    """Check every limit; figures without a value are reported as missing."""
    failures: dict[str, str] = {}
    missing: list[str] = []
    for limit in limits:
        actual = METRICS[limit.metric](stats)
        if actual is None:
            missing.append(limit.metric)
        elif limit.kind == "max" and actual > limit.value:
            failures[limit.metric] = f"{actual:g} is above the maximum {limit.value:g}"
        elif limit.kind == "min" and actual < limit.value:
            failures[limit.metric] = f"{actual:g} is below the minimum {limit.value:g}"
    return Verdict(failures=failures, missing=tuple(missing))


def dump_limits(limits: list[Limit]) -> str:
    """Write limits as the text of a criteria file that ``load_limits`` can read."""
    lines = ["[limits]"]
    lines += [f"{limit.kind}_{limit.metric} = {limit.value:g}" for limit in limits]
    return "\n".join(lines) + "\n"
