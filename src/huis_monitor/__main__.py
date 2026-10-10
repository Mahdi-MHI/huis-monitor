"""Command line entry point.

python -m huis_monitor address "Markt 87 Delft"
python -m huis_monitor area Delft --radius 15
python -m huis_monitor find Delft --radius 15
python -m huis_monitor export --out site/data
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import httpx

from huis_monitor.areas import TIMEOUT_SECONDS, AreaError, find_buurten_within, find_centre
from huis_monitor.criteria import CriteriaError, load_limits
from huis_monitor.export import export_site_data
from huis_monitor.geocode import GeocodeError, geocode
from huis_monitor.search import assess_area
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


def _report_progress(gemeente: str, number: int, total: int) -> None:
    print(f"  reading {gemeente} ({number}/{total})", file=sys.stderr)


def _print_table(items: list, with_missing: bool) -> None:
    print(
        f"{'Code':<12}{'Km':>5}  {'Gemeente':<22}{'Buurt':<30}"
        f"{'Burgl':>6}{'Viol':>6}{'Owner%':>8}{'LowInc%':>9}{'WOZ':>10}"
        + ("  No data for" if with_missing else "")
    )
    for item in items:
        buurt, stats = item.buurt, item.stats
        figures = (
            " " * 39
            if stats is None
            else f"{_show(stats.per_1000(stats.burglaries)):>6}"
            f"{_show(stats.per_1000(stats.violent_crimes)):>6}"
            f"{_show(stats.owner_occupied_pct):>8}"
            f"{_show(stats.lowest40_income_households_pct):>9}"
            f"{_show(stats.avg_woz_eur, '{:,}'):>10}"
        )
        missing = "  " + ", ".join(item.verdict.missing) if with_missing else ""
        print(
            f"{buurt.code:<12}{buurt.distance_km:>5.1f}  "
            f"{buurt.gemeente_name[:21]:<22}{buurt.name[:29]:<30}{figures}{missing}"
        )


def run_find(town: str, radius_km: float, criteria_path: Path) -> None:
    limits = load_limits(criteria_path)
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        centre, assessments = assess_area(town, radius_km, limits, client, _report_progress)

    passed = [item for item in assessments if item.verdict.passed]
    unknown = [item for item in assessments if item.verdict.unknown]
    print(f"Centre: {centre.name}")
    print(
        f"{len(assessments)} neighbourhoods within {radius_km:g} km, "
        f"checked with {criteria_path}"
    )
    print(f"  {len(passed):>4} meet every limit")
    print(f"  {len(unknown):>4} break no limit, but lack data for some figures")
    print(f"  {len(assessments) - len(passed) - len(unknown):>4} rejected")

    print()
    print("MEET EVERY LIMIT")
    _print_table(passed, with_missing=False)

    if unknown:
        print()
        print("BREAK NO LIMIT, BUT DATA IS MISSING (check these yourself)")
        _print_table(unknown, with_missing=True)

    reasons = Counter(metric for item in assessments for metric in item.verdict.failures)
    if reasons:
        print()
        print("Why neighbourhoods were rejected (one can break several limits)")
        for metric, count in reasons.most_common():
            print(f"  {metric:<34}{count:>5}")


def run_export(out_dir: Path, gemeenten: list[str]) -> int:
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        failed = export_site_data(out_dir, client, set(gemeenten) or None, _report_progress)

    print(f"Data files written to {out_dir}")
    if failed:
        print(f"Could not read {len(failed)} gemeenten: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


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

    find = commands.add_parser("find", help="list the neighbourhoods that meet the criteria")
    find.add_argument("town", help="for example Delft")
    find.add_argument("--radius", type=float, default=15.0, help="in km (default: 15)")
    find.add_argument(
        "--criteria",
        type=Path,
        default=Path("criteria.toml"),
        help="file with the limits (default: criteria.toml)",
    )

    export = commands.add_parser("export", help="write the data files for the website")
    export.add_argument("--out", type=Path, default=Path("site/data"), help="output folder")
    export.add_argument(
        "--gemeente",
        action="append",
        default=[],
        metavar="CODE",
        help="only this gemeente, for example GM0503 (may be repeated; default: all)",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "address":
            run_address(args.address)
        elif args.command == "area":
            run_area(args.town, args.radius, args.list)
        elif args.command == "find":
            run_find(args.town, args.radius, args.criteria)
        else:
            return run_export(args.out, args.gemeente)
    except (GeocodeError, StatsError, AreaError, CriteriaError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
