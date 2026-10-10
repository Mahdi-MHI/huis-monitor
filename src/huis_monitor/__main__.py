"""Command line entry point: python -m huis_monitor "Markt 87 Delft"."""

from __future__ import annotations

import argparse
import sys

from huis_monitor.geocode import GeocodeError, geocode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="huis_monitor",
        description="Look up the neighbourhood (buurt) of a Dutch address.",
    )
    parser.add_argument("address", help='for example "Markt 87 Delft"')
    args = parser.parse_args(argv)

    try:
        location = geocode(args.address)
    except GeocodeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Address : {location.address}")
    print(f"Buurt   : {location.buurt_name} ({location.buurt_code})")
    print(f"Wijk    : {location.wijk_name} ({location.wijk_code})")
    print(f"Gemeente: {location.gemeente_name} ({location.gemeente_code})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
