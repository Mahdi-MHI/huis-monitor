"""Command line entry point: python -m huis_monitor "Markt 87 Delft"."""

from __future__ import annotations

import argparse
import sys

from huis_monitor.geocode import GeocodeError, geocode
from huis_monitor.stats import NeighbourhoodStats, StatsError, fetch_stats


def _show(value, pattern: str = "{}") -> str:
    return "n/a" if value is None else pattern.format(value)


def _crime_line(stats: NeighbourhoodStats, count: int | None) -> str:
    return f"{_show(stats.per_1000(count))} per 1,000 residents ({_show(count)} registered)"


def format_stats(stats: NeighbourhoodStats) -> str:
    lines = [
        f"Residents            : {_show(stats.residents, '{:,}')}",
        f"Origin Netherlands   : {_show(stats.origin_nl_pct, '{}%')}",
        f"Origin rest of Europe: {_show(stats.origin_europe_pct, '{}%')}",
        f"Origin outside Europe: {_show(stats.origin_outside_europe_pct, '{}%')}",
        f"Density              : {_show(stats.density_per_km2, '{:,} per km2')}",
        f"Average WOZ value    : {_show(stats.avg_woz_eur, 'EUR {:,}')}",
        f"Owner-occupied homes : {_show(stats.owner_occupied_pct, '{}%')}",
        f"Income per resident  : {_show(stats.avg_income_eur, 'EUR {:,}')}",
        f"Low-income households: {_show(stats.lowest40_income_households_pct, '{}%')}",
        f"Urbanity (1-5)       : {_show(stats.urbanity)}",
        f"Crime figures for {_show(stats.crime_year)}",
        f"  Total      : {_crime_line(stats, stats.crimes_total)}",
        f"  Burglary   : {_crime_line(stats, stats.burglaries)}",
        f"  Violence   : {_crime_line(stats, stats.violent_crimes)}",
        f"  Vandalism  : {_crime_line(stats, stats.vandalism)}",
        f"  Bike theft : {_crime_line(stats, stats.bike_thefts)}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="huis_monitor",
        description="Show the neighbourhood (buurt) of a Dutch address and its key figures.",
    )
    parser.add_argument("address", help='for example "Markt 87 Delft"')
    args = parser.parse_args(argv)

    try:
        location = geocode(args.address)
        stats = fetch_stats(location.buurt_code)
    except (GeocodeError, StatsError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Address : {location.address}")
    print(f"Buurt   : {location.buurt_name} ({location.buurt_code})")
    print(f"Wijk    : {location.wijk_name} ({location.wijk_code})")
    print(f"Gemeente: {location.gemeente_name} ({location.gemeente_code})")
    print()
    print(format_stats(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
