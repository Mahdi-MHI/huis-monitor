import httpx
import pytest

from huis_monitor.geocode import GeocodeError, Location, geocode

DOC = {
    "weergavenaam": "Markt 87, 2611GS Delft",
    "postcode": "2611GS",
    "buurtcode": "BU05031100",
    "buurtnaam": "Centrum",
    "wijkcode": "WK050311",
    "wijknaam": "Binnenstad",
    "gemeentecode": "0503",
    "gemeentenaam": "Delft",
}


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def reply_with(docs, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"response": {"docs": docs}})

    return handler


def test_returns_location_for_known_address():
    location = geocode("Markt 87 Delft", client=make_client(reply_with([DOC])))

    assert location == Location(
        address="Markt 87, 2611GS Delft",
        postcode="2611GS",
        buurt_code="BU05031100",
        buurt_name="Centrum",
        wijk_code="WK050311",
        wijk_name="Binnenstad",
        gemeente_code="0503",
        gemeente_name="Delft",
    )


def test_asks_pdok_for_one_address_result():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json={"response": {"docs": [DOC]}})

    geocode("  Markt 87 Delft  ", client=make_client(handler))

    assert seen == {"q": "Markt 87 Delft", "fq": "type:adres", "rows": "1"}


def test_unknown_address_raises():
    with pytest.raises(GeocodeError, match="No address found"):
        geocode("Nergensstraat 999", client=make_client(reply_with([])))


def test_empty_query_raises():
    with pytest.raises(GeocodeError, match="Empty address"):
        geocode("   ")


def test_result_without_buurt_raises():
    doc = {key: value for key, value in DOC.items() if key != "buurtcode"}

    with pytest.raises(GeocodeError, match="buurtcode"):
        geocode("Markt 87 Delft", client=make_client(reply_with([doc])))


def test_server_error_raises():
    with pytest.raises(GeocodeError, match="PDOK lookup failed"):
        geocode("Markt 87 Delft", client=make_client(reply_with([], status=500)))
