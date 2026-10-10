"""Assess every neighbourhood around a town against the criteria."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from huis_monitor.areas import Buurt, Centre, find_buurten_within, find_centre
from huis_monitor.criteria import Limit, Verdict, evaluate
from huis_monitor.stats import NeighbourhoodStats, fetch_stats_for_gemeente


@dataclass(frozen=True)
class Assessment:
    """A neighbourhood, its figures (if CBS has any) and the verdict."""

    buurt: Buurt
    stats: NeighbourhoodStats | None
    verdict: Verdict


def assess_area(
    town: str,
    radius_km: float,
    limits: list[Limit],
    client: httpx.Client,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> tuple[Centre, list[Assessment]]:
    """Return the centre of ``town`` and an assessment of every buurt in range.

    ``on_progress(gemeente_name, number, total)`` is called before each
    gemeente is read, because that is the slow part.
    """
    centre = find_centre(town, client)
    buurten = find_buurten_within(centre, radius_km, client)

    gemeenten: dict[str, str] = {}
    for buurt in buurten:
        gemeenten.setdefault(buurt.gemeente_code, buurt.gemeente_name)

    all_stats: dict[str, NeighbourhoodStats] = {}
    for number, (code, name) in enumerate(gemeenten.items(), start=1):
        if on_progress is not None:
            on_progress(name, number, len(gemeenten))
        all_stats.update(fetch_stats_for_gemeente(code, client))

    assessments = []
    for buurt in buurten:
        stats = all_stats.get(buurt.code)
        if stats is None:
            verdict = Verdict(failures={}, missing=("figures",))
        else:
            verdict = evaluate(stats, limits)
        assessments.append(Assessment(buurt=buurt, stats=stats, verdict=verdict))
    return centre, assessments
