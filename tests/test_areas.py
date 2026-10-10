import httpx
import pytest

from huis_monitor import areas
from huis_monitor.areas import AreaError, Centre, find_buurten_within, find_centre

CENTRE = Centre(name="Delft", x=84_000.0, y=447_000.0)


def square(x: float, y: float, size: float = 200.0) -> dict:
    """A square outline whose centre is exactly (x, y)."""
    half = size / 2
    ring = [
        [x - half, y - half],
        [x + half, y - half],
        [x + half, y + half],
        [x - half, y + half],
        [x - half, y - half],
    ]
    return {"type": "MultiPolygon", "coordinates": [[ring]]}


def feature(code: str, x: float, y: float, water: str = "NEE", residents: int = 1000) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "buurtcode": code,
            "buurtnaam": f"Buurt {code}",
            "gemeentecode": "GM0503",
            "gemeentenaam": "Delft",
            "water": water,
            "aantalInwoners": residents,
        },
        "geometry": square(x, y),
    }


def wfs_client(pages: list[list[dict]], seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.query.decode())
        index = int(request.url.params["startIndex"]) // areas.PAGE_SIZE
        return httpx.Response(200, json={"type": "FeatureCollection", "features": pages[index]})

    return httpx.Client(transport=httpx.MockTransport(handler))


def search_client(docs: list[dict], status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["fq"] == "type:woonplaats"
        return httpx.Response(status, json={"response": {"docs": docs}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_find_centre_reads_rd_coordinates():
    doc = {"weergavenaam": "Delft, Delft, Zuid-Holland", "centroide_rd": "POINT(84414.5 447468.25)"}

    centre = find_centre(" Delft ", search_client([doc]))

    assert centre == Centre(name="Delft, Delft, Zuid-Holland", x=84414.5, y=447468.25)


def test_unknown_town_raises():
    with pytest.raises(AreaError, match="No town found"):
        find_centre("Nergenshuizen", search_client([]))


def test_town_without_centre_point_raises():
    with pytest.raises(AreaError, match="no usable centre point"):
        find_centre("Delft", search_client([{"weergavenaam": "Delft"}]))


def test_keeps_only_buurten_inside_radius_nearest_first():
    page = [
        feature("BU_FAR", 84_000, 447_000 + 6_000),
        feature("BU_NEAR", 84_000 + 3_000, 447_000 + 4_000),
        feature("BU_CENTRE", 84_000, 447_000),
    ]

    buurten = find_buurten_within(CENTRE, 5, wfs_client([page]))

    assert [(b.code, b.distance_km) for b in buurten] == [("BU_CENTRE", 0.0), ("BU_NEAR", 5.0)]


def test_skips_water_and_reads_missing_residents_as_none():
    page = [
        feature("BU_WATER", 84_000, 447_000, water="JA"),
        feature("BU_EMPTY", 84_000, 447_100, residents=-99997),
    ]

    buurten = find_buurten_within(CENTRE, 5, wfs_client([page]))

    assert [b.code for b in buurten] == ["BU_EMPTY"]
    assert buurten[0].residents is None


def test_requests_a_box_around_the_centre():
    seen: list = []

    find_buurten_within(CENTRE, 15, wfs_client([[]], seen))

    # The box is sent with plain commas, the form checked against the live service.
    assert "&bbox=69000,432000,99000,462000&" in seen[0]
    assert "typeName=wijkenbuurten:buurten" in seen[0]


def test_reads_every_page(monkeypatch):
    monkeypatch.setattr(areas, "PAGE_SIZE", 2)
    pages = [
        [feature("BU_A", 84_000, 447_000), feature("BU_B", 84_100, 447_000)],
        [feature("BU_C", 84_200, 447_000)],
    ]

    buurten = find_buurten_within(CENTRE, 5, wfs_client(pages))

    assert [b.code for b in buurten] == ["BU_A", "BU_B", "BU_C"]


def test_radius_must_be_positive():
    with pytest.raises(AreaError, match="greater than zero"):
        find_buurten_within(CENTRE, 0, wfs_client([[]]))


def test_map_server_error_raises():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503)))

    with pytest.raises(AreaError, match="map request failed"):
        find_buurten_within(CENTRE, 5, client)


def test_buurt_gets_an_outline_in_longitude_and_latitude():
    page = [feature("BU_A", 155_000, 463_000)]  # the origin of the Dutch grid

    centre = Centre("Amersfoort", 155_000.0, 463_000.0)

    buurt = find_buurten_within(centre, 5, wfs_client([page]))[0]

    assert len(buurt.outline) == 1
    ring = buurt.outline[0]
    assert len(ring) == 5 and ring[0] == ring[-1]
    longitudes = [lon for lon, _ in ring]
    latitudes = [lat for _, lat in ring]
    assert min(longitudes) < 5.38721 < max(longitudes)
    assert min(latitudes) < 52.15517 < max(latitudes)
