"""Neighbourhood (buurt) statistics from CBS and police open data."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

# Kerncijfers wijken en buurten, newest first. Income figures are published
# about two years late, so missing values are filled from the older table.
KERNCIJFERS_URLS = (
    "https://opendata.cbs.nl/ODataApi/odata/86165NED/TypedDataSet",  # 2025
    "https://opendata.cbs.nl/ODataApi/odata/85984NED/TypedDataSet",  # 2024
)
# Geregistreerde misdrijven per wijk en buurt, yearly figures (police data).
CRIME_URL = "https://dataderden.cbs.nl/ODataApi/OData/47018NED/TypedDataSet"
TIMEOUT_SECONDS = 20.0

COL_RESIDENTS = "AantalInwoners_5"
COL_ORIGIN_NL = "Nederland_17"
COL_ORIGIN_EUROPE = "EuropaExclusiefNederland_18"
COL_ORIGIN_OUTSIDE_EUROPE = "BuitenEuropa_19"
COL_DENSITY = "Bevolkingsdichtheid_34"
COL_WOZ = "GemiddeldeWOZWaardeVanWoningen_39"
COL_OWNER_OCCUPIED = "Koopwoningen_47"
COL_INCOME = "GemiddeldInkomenPerInwoner_78"
COL_LOW_INCOME = "k_40HuishoudensMetLaagsteInkomen_84"
COL_URBANITY = "MateVanStedelijkheid_120"
KERNCIJFERS_COLUMNS = (
    COL_RESIDENTS,
    COL_ORIGIN_NL,
    COL_ORIGIN_EUROPE,
    COL_ORIGIN_OUTSIDE_EUROPE,
    COL_DENSITY,
    COL_WOZ,
    COL_OWNER_OCCUPIED,
    COL_INCOME,
    COL_LOW_INCOME,
    COL_URBANITY,
)

CRIME_TOTAL = "0.0.0"
CRIME_BURGLARY = "1.1.1"
CRIME_BIKE_THEFT = "1.2.3"
CRIME_VANDALISM = "2.2.1"
# Murder, public violence, threat, assault, street robbery, hold-up.
CRIME_VIOLENT = ("1.4.2", "1.4.3", "1.4.4", "1.4.5", "1.4.6", "1.4.7")


class StatsError(Exception):
    """Raised when statistics for a neighbourhood cannot be retrieved."""


@dataclass(frozen=True)
class NeighbourhoodStats:
    """Key figures for one buurt. ``None`` means CBS publishes no value."""

    buurt_code: str
    residents: int | None
    origin_nl_pct: float | None
    origin_europe_pct: float | None
    origin_outside_europe_pct: float | None
    density_per_km2: int | None
    avg_woz_eur: int | None
    owner_occupied_pct: float | None
    avg_income_eur: int | None
    lowest40_income_households_pct: float | None
    urbanity: int | None  # 1 = very urban ... 5 = rural
    crime_year: int | None
    crimes_total: int | None
    burglaries: int | None
    violent_crimes: int | None
    vandalism: int | None
    bike_thefts: int | None

    def per_1000(self, count: int | None) -> float | None:
        """Express a count per 1,000 residents."""
        if count is None or not self.residents:
            return None
        return round(count / self.residents * 1000, 1)


def fetch_stats(buurt_code: str, client: httpx.Client | None = None) -> NeighbourhoodStats:
    """Return the key figures for ``buurt_code`` (for example "BU05031104")."""
    if client is None:
        with httpx.Client(timeout=TIMEOUT_SECONDS) as own_client:
            return fetch_stats(buurt_code, own_client)

    figures = _fetch_kerncijfers(buurt_code, client)
    crime_year, crimes = _fetch_crimes(buurt_code, client)

    residents = _as_int(figures[COL_RESIDENTS])
    violent = [crimes[code] for code in CRIME_VIOLENT if crimes.get(code) is not None]
    return NeighbourhoodStats(
        buurt_code=buurt_code,
        residents=residents,
        origin_nl_pct=_share(figures[COL_ORIGIN_NL], residents),
        origin_europe_pct=_share(figures[COL_ORIGIN_EUROPE], residents),
        origin_outside_europe_pct=_share(figures[COL_ORIGIN_OUTSIDE_EUROPE], residents),
        density_per_km2=_as_int(figures[COL_DENSITY]),
        avg_woz_eur=_thousands(figures[COL_WOZ]),
        owner_occupied_pct=figures[COL_OWNER_OCCUPIED],
        avg_income_eur=_thousands(figures[COL_INCOME]),
        lowest40_income_households_pct=figures[COL_LOW_INCOME],
        urbanity=_as_int(figures[COL_URBANITY]),
        crime_year=crime_year,
        crimes_total=crimes.get(CRIME_TOTAL),
        burglaries=crimes.get(CRIME_BURGLARY),
        violent_crimes=sum(violent) if violent else None,
        vandalism=crimes.get(CRIME_VANDALISM),
        bike_thefts=crimes.get(CRIME_BIKE_THEFT),
    )


def _get_rows(client: httpx.Client, url: str, params: dict[str, str]) -> list[dict]:
    try:
        response = client.get(url, params={**params, "$format": "json"})
        response.raise_for_status()
        return response.json()["value"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise StatsError(f"CBS request failed ({url}): {exc}") from exc


def _fetch_kerncijfers(buurt_code: str, client: httpx.Client) -> dict:
    """Take each column from the newest table that has a value for it."""
    figures: dict = dict.fromkeys(KERNCIJFERS_COLUMNS)
    found = False
    for url in KERNCIJFERS_URLS:
        rows = _get_rows(
            client,
            url,
            {
                "$filter": f"WijkenEnBuurten eq '{buurt_code}'",
                "$select": ",".join(KERNCIJFERS_COLUMNS),
            },
        )
        if not rows:
            continue
        found = True
        for column in KERNCIJFERS_COLUMNS:
            if figures[column] is None:
                figures[column] = rows[0].get(column)
    if not found:
        raise StatsError(f"No CBS figures found for {buurt_code}")
    return figures


def _fetch_crimes(buurt_code: str, client: httpx.Client) -> tuple[int | None, dict[str, int]]:
    """Return the latest year with figures and its counts per crime code."""
    rows = _get_rows(
        client,
        CRIME_URL,
        {
            "$filter": f"WijkenEnBuurten eq '{buurt_code}'",
            "$select": "SoortMisdrijf,Perioden,GeregistreerdeMisdrijven_1",
        },
    )
    per_year: dict[int, dict[str, int]] = {}
    for row in rows:
        count = row.get("GeregistreerdeMisdrijven_1")
        if count is None:
            continue
        year = int(row["Perioden"][:4])
        per_year.setdefault(year, {})[row["SoortMisdrijf"].strip()] = int(count)

    years_with_total = [year for year, counts in per_year.items() if CRIME_TOTAL in counts]
    if not years_with_total:
        return None, {}
    latest = max(years_with_total)
    return latest, per_year[latest]


def _as_int(value: float | None) -> int | None:
    return None if value is None else int(value)


def _thousands(value: float | None) -> int | None:
    """CBS reports euro amounts in thousands."""
    return None if value is None else round(value * 1000)


def _share(part: float | None, total: int | None) -> float | None:
    if part is None or not total:
        return None
    return round(part / total * 100, 1)
