"""Find the CBS neighbourhood (buurt) of a Dutch address via PDOK Locatieserver."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

PDOK_URL = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"
TIMEOUT_SECONDS = 10.0


class GeocodeError(Exception):
    """Raised when an address cannot be resolved to a neighbourhood."""


@dataclass(frozen=True)
class Location:
    """An address together with the CBS areas it belongs to."""

    address: str
    postcode: str | None
    buurt_code: str
    buurt_name: str
    wijk_code: str
    wijk_name: str
    gemeente_code: str
    gemeente_name: str


def geocode(query: str, client: httpx.Client | None = None) -> Location:
    """Return the best-matching address for ``query``.

    ``query`` is free text, for example "Markt 87 Delft" or "2611GS 87".
    Pass ``client`` to reuse a connection (or to inject a fake one in tests).
    """
    query = query.strip()
    if not query:
        raise GeocodeError("Empty address")

    params = {"q": query, "fq": "type:adres", "rows": 1}
    try:
        if client is None:
            with httpx.Client(timeout=TIMEOUT_SECONDS) as own_client:
                response = own_client.get(PDOK_URL, params=params)
        else:
            response = client.get(PDOK_URL, params=params)
        response.raise_for_status()
        docs = response.json()["response"]["docs"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise GeocodeError(f"PDOK lookup failed for {query!r}: {exc}") from exc

    if not docs:
        raise GeocodeError(f"No address found for {query!r}")

    doc = docs[0]
    try:
        return Location(
            address=doc["weergavenaam"],
            postcode=doc.get("postcode"),
            buurt_code=doc["buurtcode"],
            buurt_name=doc["buurtnaam"],
            wijk_code=doc["wijkcode"],
            wijk_name=doc["wijknaam"],
            gemeente_code=doc["gemeentecode"],
            gemeente_name=doc["gemeentenaam"],
        )
    except KeyError as exc:
        raise GeocodeError(f"PDOK result for {query!r} has no field {exc}") from exc
