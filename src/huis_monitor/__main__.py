"""Command line entry point.

python -m huis_monitor address "Markt 87 Delft"
python -m huis_monitor area Delft --radius 15
"""

from __future__ import annotations

import argparse
import sys

import httpx

from huis_monitor.areas import TIMEOUT_SECONDS, AreaError, find_buurten_within, find_centre
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


def run_address(address: str) -> None:
    location = geocode(address)
    stats = fetch_stats(location.buurt_code)

    print(f"Address : {location.address}")
    print(f"Buurt   : {location.buurt_name} ({location.buurt_code})")
    print(f"Wijk    : {location.wijk_name} ({location.wijk_code})")
    print(f"Gemeente: {location.gemeente_name} ({location.gemeente_code})")
    print()
    print(format_stats(stats))


def run_area(town: str, radius_km: float, show_all: bool) -> None:
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        centre = find_centre(town, client)
        buurten = find_buurten_within(centre, radius_km, client)

    print(f"Centre: {centre.name}")
    print(f"Found {len(buurten)} neighbourhoods within {radius_km:g} km")
    print()

    per_gemeente: dict[str, list] = {}
    for buurt in buurten:
        per_gemeente.setdefault(buurt.gemeente_name, []).append(buurt)
    print(f"{'Gemeente':<28}{'Buurten':>8}{'Nearest':>10}")
    for name, group in sorted(per_gemeente.items(), key=lambda item: item[1][0].distance_km):
        print(f"{name:<28}{len(group):>8}{group[0].distance_km:>7.1f} km")

    if show_all:
        print()
        print(f"{'Code':<12}{'Km':>5}  {'Gemeente':<26}Buurt")
        for buurt in buurten:
            print(
                f"{buurt.code:<12}{buurt.distance_km:>5.1f}  "
                f"{buurt.gemeente_name:<26}{buurt.name}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="huis_monitor",
        description="Explore Dutch neighbourhoods (buurten) and their key figures.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    address = commands.add_parser("address", help="show the figures for one address")
    address.add_argument("address", help='for example "Markt 87 Delft"')

    area = commands.add_parser("area", help="list the neighbourhoods around a town")
    area.add_argument("town", help="for example Delft")
    area.add_argument("--radius", type=float, default=15.0, help="in km (default: 15)")
    area.add_argument("--list", action="store_true", help="also print every neighbourhood")

    args = parser.parse_args(argv)
    try:
        if args.command == "address":
            run_address(args.address)
        else:
            run_area(args.town, args.radius, args.list)
    except (GeocodeError, StatsError, AreaError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
