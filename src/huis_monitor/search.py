"""Load every neighbourhood around a town and assess it against the criteria."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from huis_monitor.areas import Buurt, Centre, find_buurten_within, find_centre
from huis_monitor.criteria import Limit, Verdict, evaluate
from huis_monitor.stats import NeighbourhoodStats, fetch_stats_for_gemeente


@dataclass(frozen=True)
class AreaData:
    """Everything that was read for one town and radius; independent of limits."""

    centre: Centre
    radius_km: float
    buurten: list[Buurt]
    stats: dict[str, NeighbourhoodStats]


@dataclass(frozen=True)
class Assessment:
    """A neighbourhood, its figures (if CBS has any) and the verdict."""

    buurt: Buurt
    stats: NeighbourhoodStats | None
    verdict: Verdict


def load_area(
    town: str,
    radius_km: float,
    client: httpx.Client,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> AreaData:
    """Read the neighbourhoods within ``radius_km`` of ``town`` and their figures.

    This is the slow part (about a minute for 15 km around a city).
    ``on_progress(gemeente_name, number, total)`` is called before each
    gemeente is read.
    """
    centre = find_centre(town, client)
    buurten = find_buurten_within(centre, radius_km, client)

    gemeenten: dict[str, str] = {}
    for buurt in buurten:
        gemeenten.setdefault(buurt.gemeente_code, buurt.gemeente_name)

    stats: dict[str, NeighbourhoodStats] = {}
    for number, (code, name) in enumerate(gemeenten.items(), start=1):
        if on_progress is not None:
            on_progress(name, number, len(gemeenten))
        stats.update(fetch_stats_for_gemeente(code, client))

    return AreaData(centre=centre, radius_km=radius_km, buurten=buurten, stats=stats)


def assess(area: AreaData, limits: list[Limit]) -> list[Assessment]:
    """Judge every neighbourhood of ``area``; fast, so limits can change freely."""
    assessments = []
    for buurt in area.buurten:
        stats = area.stats.get(buurt.code)
        if stats is None:
            verdict = Verdict(failures={}, missing=("figures",))
        else:
            verdict = evaluate(stats, limits)
        assessments.append(Assessment(buurt=buurt, stats=stats, verdict=verdict))
    return assessments


def assess_area(
    town: str,
    radius_km: float,
    limits: list[Limit],
    client: httpx.Client,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> tuple[Centre, list[Assessment]]:
    """Load an area and assess it in one call (used by the command line)."""
    area = load_area(town, radius_km, client, on_progress)
    return area.centre, assess(area, limits)
