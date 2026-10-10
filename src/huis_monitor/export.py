"""Write the data files that the website reads.

Layout inside the output folder:

    index.json         when the data was made, national averages, list of gemeenten
    gm/GM0503.json     every neighbourhood of one gemeente, with figures and border
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

import httpx

from huis_monitor.areas import Buurt, fetch_all_buurten
from huis_monitor.criteria import METRICS
from huis_monitor.figures import CRIMES, GROUPS
from huis_monitor.stats import (
    NeighbourhoodStats,
    StatsError,
    fetch_stats_for_gemeente,
    latest_crime_period,
)

ATTEMPTS = 3
PAUSE_SECONDS = 5.0
# Crime figures: name of the count behind each "per 1,000" figure.
CRIME_COUNTS = {figure.metric: figure.metric.removesuffix("_per_1000") for figure in CRIMES}


def catalogue() -> dict:
    """Names and labels of the figures, so the website needs no copy of them."""
    return {
        "groups": [
            {
                "title": group.title,
                "figures": [
                    {"metric": figure.metric, "label": figure.label} for figure in group.figures
                ],
            }
            for group in GROUPS
        ],
        "crimes": [
            {"metric": figure.metric, "label": figure.label, "count": CRIME_COUNTS[figure.metric]}
            for figure in CRIMES
        ],
    }


def crime_count(stats: NeighbourhoodStats, name: str) -> int | None:
    """Number of registered crimes of one kind, for example "burglaries"."""
    if name in stats.other_crimes:
        return stats.other_crimes[name]
    return getattr(stats, name, None)


def figures_of(stats: NeighbourhoodStats) -> dict[str, float]:
    """Every published figure of one neighbourhood, by name."""
    figures = {}
    for metric, read in METRICS.items():
        value = read(stats)
        if value is not None:
            figures[metric] = value
    return figures


def counts_of(stats: NeighbourhoodStats) -> dict[str, int]:
    counts = {}
    for name in CRIME_COUNTS.values():
        count = crime_count(stats, name)
        if count is not None:
            counts[name] = count
    return counts


def average_of(all_stats: Iterable[NeighbourhoodStats]) -> dict[str, float]:
    """Figures of a group of neighbourhoods taken together.

    Residents are added up, crime figures are recomputed from the counts, and
    every other figure is averaged with large neighbourhoods counting more.
    """
    populated = [stats for stats in all_stats if stats.residents]
    if not populated:
        return {}

    average: dict[str, float] = {"residents": sum(stats.residents for stats in populated)}
    for metric, read in METRICS.items():
        if metric == "residents":
            continue
        total = weight = 0.0
        if metric in CRIME_COUNTS:
            for stats in populated:
                count = crime_count(stats, CRIME_COUNTS[metric])
                if count is not None:
                    total += count * 1000
                    weight += stats.residents
        else:
            for stats in populated:
                value = read(stats)
                if value is not None:
                    total += value * stats.residents
                    weight += stats.residents
        if weight:
            average[metric] = round(total / weight, 1)
    return average


def _bounds(buurten: list[Buurt]) -> list[float]:
    """Smallest box around the neighbourhoods: west, south, east, north."""
    points = [point for buurt in buurten for ring in buurt.outline for point in ring]
    points += [(buurt.lon, buurt.lat) for buurt in buurten]
    longitudes = [lon for lon, _ in points]
    latitudes = [lat for _, lat in points]
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def _write(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, ensure_ascii=False, separators=(",", ":")))


def _fetch_with_retries(
    gemeente_code: str, client: httpx.Client, period: str
) -> dict[str, NeighbourhoodStats]:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return fetch_stats_for_gemeente(gemeente_code, client, period)
        except StatsError:
            if attempt == ATTEMPTS:
                raise
            time.sleep(PAUSE_SECONDS)
    raise AssertionError("unreachable")


def export_site_data(
    out_dir: Path,
    client: httpx.Client,
    only_gemeenten: set[str] | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> list[str]:
    """Write all data files and return the names of gemeenten that failed.

    ``only_gemeenten`` limits the work to some gemeente codes ("GM0503"), which
    is handy for a quick trial; by default the whole country is written.
    """
    per_gemeente: dict[str, list[Buurt]] = {}
    for buurt in fetch_all_buurten(client):
        if only_gemeenten is None or buurt.gemeente_code in only_gemeenten:
            per_gemeente.setdefault(buurt.gemeente_code, []).append(buurt)

    period = latest_crime_period(client)
    index_entries = []
    failed: list[str] = []
    everything: list[NeighbourhoodStats] = []

    for number, (code, buurten) in enumerate(sorted(per_gemeente.items()), start=1):
        name = buurten[0].gemeente_name
        if on_progress is not None:
            on_progress(name, number, len(per_gemeente))
        try:
            stats = _fetch_with_retries(code, client, period)
        except StatsError:
            failed.append(name)
            continue

        entries = []
        for buurt in buurten:
            entry = {
                "code": buurt.code,
                "name": buurt.name,
                "lat": buurt.lat,
                "lon": buurt.lon,
                "outline": buurt.outline,
            }
            if buurt.code in stats:
                entry["figures"] = figures_of(stats[buurt.code])
                entry["counts"] = counts_of(stats[buurt.code])
            entries.append(entry)

        known = [stats[buurt.code] for buurt in buurten if buurt.code in stats]
        everything += known
        _write(
            out_dir / "gm" / f"{code}.json",
            {"code": code, "name": name, "average": average_of(known), "buurten": entries},
        )
        index_entries.append(
            {"code": code, "name": name, "bounds": _bounds(buurten), "buurten": len(buurten)}
        )

    _write(
        out_dir / "index.json",
        {
            "generated": datetime.now(UTC).strftime("%Y-%m-%d"),
            "crime_year": int(period[:4]),
            "complete": only_gemeenten is None and not failed,
            "average": average_of(everything),
            **catalogue(),
            "gemeenten": index_entries,
        },
    )
    return failed
