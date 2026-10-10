"""Find all neighbourhoods (buurten) within a radius of a town."""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass

import httpx

from huis_monitor.geo import rd_to_wgs84

PDOK_SEARCH_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
BUURTEN_WFS_URL = "https://service.pdok.nl/cbs/wijkenbuurten/2025/wfs/v1_0"
PAGE_SIZE = 1000
TIMEOUT_SECONDS = 60.0
NO_DATA = -99990  # CBS marks missing numbers with values below this

_POINT = re.compile(r"POINT\(([-\d.]+) ([-\d.]+)\)")


class AreaError(Exception):
    """Raised when a town or its surrounding neighbourhoods cannot be found."""


@dataclass(frozen=True)
class Centre:
    """Centre point of a town in RD coordinates (the Dutch grid, in metres)."""

    name: str
    x: float
    y: float

    @property
    def lat_lon(self) -> tuple[float, float]:
        return rd_to_wgs84(self.x, self.y)


@dataclass(frozen=True)
class Buurt:
    """A neighbourhood and its distance to the chosen centre.

    ``outline`` holds the border for drawing on a map: one ring per polygon,
    each ring a tuple of ``(longitude, latitude)`` points.
    """

    code: str
    name: str
    gemeente_code: str
    gemeente_name: str
    residents: int | None
    distance_km: float
    outline: tuple[tuple[tuple[float, float], ...], ...] = ()


def find_centre(town: str, client: httpx.Client) -> Centre:
    """Return the centre point of ``town`` (a woonplaats such as "Delft")."""
    town = town.strip()
    if not town:
        raise AreaError("Empty town name")

    params = {"q": town, "fq": "type:woonplaats", "rows": 1}
    try:
        response = client.get(PDOK_SEARCH_URL, params=params)
        response.raise_for_status()
        docs = response.json()["response"]["docs"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise AreaError(f"PDOK lookup failed for {town!r}: {exc}") from exc

    if not docs:
        raise AreaError(f"No town found for {town!r}")

    doc = docs[0]
    match = _POINT.fullmatch(doc.get("centroide_rd", ""))
    if match is None:
        raise AreaError(f"PDOK result for {town!r} has no usable centre point")
    return Centre(name=doc.get("weergavenaam", town), x=float(match[1]), y=float(match[2]))


def find_buurten_within(centre: Centre, radius_km: float, client: httpx.Client) -> list[Buurt]:
    """Return the buurten whose centre lies within ``radius_km``, nearest first."""
    if radius_km <= 0:
        raise AreaError("Radius must be greater than zero")

    radius_m = radius_km * 1000
    bbox = (
        f"{centre.x - radius_m:.0f},{centre.y - radius_m:.0f},"
        f"{centre.x + radius_m:.0f},{centre.y + radius_m:.0f}"
    )

    found: dict[str, Buurt] = {}
    start = 0
    while True:
        features = _fetch_page(client, bbox, start)
        for feature in features:
            buurt = _to_buurt(feature, centre)
            if buurt is not None and buurt.distance_km <= radius_km:
                found[buurt.code] = buurt
        if len(features) < PAGE_SIZE:
            break
        start += PAGE_SIZE

    return sorted(found.values(), key=lambda buurt: (buurt.distance_km, buurt.code))


def _fetch_page(client: httpx.Client, bbox: str, start: int) -> list[dict]:
    # The query string is written out by hand on purpose, so the commas in the
    # bbox are sent as plain commas: that is the form that was checked against
    # the live service. httpx's ``params`` would percent-encode them.
    url = (
        f"{BUURTEN_WFS_URL}?service=WFS&version=2.0.0&request=GetFeature"
        f"&typeName=wijkenbuurten:buurten&bbox={bbox}"
        f"&count={PAGE_SIZE}&startIndex={start}&outputFormat=application/json"
    )
    try:
        response = client.get(url)
        response.raise_for_status()
        return response.json()["features"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise AreaError(f"PDOK neighbourhood map request failed: {exc}") from exc


def _to_buurt(feature: dict, centre: Centre) -> Buurt | None:
    """Convert a map feature; water and foreign areas give ``None``."""
    props = feature["properties"]
    if props.get("water") != "NEE":
        return None

    x, y = _centroid(feature["geometry"])
    residents = props.get("aantalInwoners")
    return Buurt(
        code=props["buurtcode"],
        name=props["buurtnaam"],
        gemeente_code=props["gemeentecode"],
        gemeente_name=props["gemeentenaam"],
        residents=None if residents is None or residents < NO_DATA else int(residents),
        distance_km=round(math.hypot(x - centre.x, y - centre.y) / 1000, 1),
        outline=_outline(feature["geometry"]),
    )


def _polygons(geometry: dict) -> list:
    """Return the polygons of a Polygon or MultiPolygon geometry."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    return geometry["coordinates"]


def _outline(geometry: dict) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Outer border of every polygon as (longitude, latitude) points."""
    rings = []
    for polygon in _polygons(geometry):
        ring = []
        for x, y in polygon[0]:
            lat, lon = rd_to_wgs84(x, y)
            ring.append((round(lon, 5), round(lat, 5)))
        rings.append(tuple(ring))
    return tuple(rings)


def _centroid(geometry: dict) -> tuple[float, float]:
    """Centre of gravity of the largest polygon in a (Multi)Polygon."""
    polygons = _polygons(geometry)

    best_area = -1.0
    best_point = (0.0, 0.0)
    for polygon in polygons:
        ring = polygon[0]  # outer boundary; holes are ignored
        area = cx = cy = 0.0
        for (x1, y1), (x2, y2) in itertools.pairwise(ring):
            cross = x1 * y2 - x2 * y1
            area += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        if area == 0:
            continue
        if abs(area) > best_area:
            best_area = abs(area)
            best_point = (cx / (3 * area), cy / (3 * area))
    if best_area < 0:
        raise AreaError("Neighbourhood without a usable outline")
    return best_point
