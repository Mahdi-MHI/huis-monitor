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
CRIME_BASE_URL = "https://dataderden.cbs.nl/ODataApi/odata/47018NED"
CRIME_URL = f"{CRIME_BASE_URL}/TypedDataSet"
CRIME_BULK_URL = f"{CRIME_BASE_URL}/UntypedDataSet"
CRIME_PERIODS_URL = f"{CRIME_BASE_URL}/Perioden"
CRIME_COLUMNS = "WijkenEnBuurten,SoortMisdrijf,Perioden,GeregistreerdeMisdrijven_1"
CRIME_TYPE_COUNT = 59  # rows per buurt per year in the crime table
MAX_ROWS_PER_REQUEST = 9000  # CBS refuses requests for more than 10,000 rows
TIMEOUT_SECONDS = 60.0

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
    return _build(buurt_code, figures, crime_year, crimes)


def fetch_stats_for_gemeente(
    gemeente_code: str, client: httpx.Client
) -> dict[str, NeighbourhoodStats]:
    """Return the key figures of every buurt in a gemeente, keyed by buurt code.

    ``gemeente_code`` may be written as "GM0503" or "0503".
    """
    prefix = "BU" + gemeente_code.removeprefix("GM")

    figures: dict[str, dict] = {}
    columns = ",".join(("WijkenEnBuurten", *KERNCIJFERS_COLUMNS))
    for url in KERNCIJFERS_URLS:
        query = f"{url}?$filter=startswith(WijkenEnBuurten,'{prefix}')&$select={columns}"
        for row in _get_rows_by_url(client, query):
            code = row["WijkenEnBuurten"].strip()
            merged = figures.setdefault(code, dict.fromkeys(KERNCIJFERS_COLUMNS))
            for column in KERNCIJFERS_COLUMNS:
                if merged[column] is None:
                    merged[column] = row.get(column)

    # One request per gemeente, unless it is so large that the answer would
    # exceed the row limit; then one request per wijk (first 8 characters).
    if len(figures) * CRIME_TYPE_COUNT <= MAX_ROWS_PER_REQUEST:
        prefixes = [prefix]
    else:
        prefixes = sorted({code[:8] for code in figures})

    period = _latest_crime_period(client)
    crime_year = int(period[:4])
    crimes: dict[str, dict[str, int]] = {}
    for crime_prefix in prefixes:
        query = (
            f"{CRIME_BULK_URL}?$filter=startswith(WijkenEnBuurten,'{crime_prefix}')"
            f" and Perioden eq '{period}'&$select={CRIME_COLUMNS}"
        )
        for row in _get_rows_by_url(client, query):
            count = _as_count(row.get("GeregistreerdeMisdrijven_1"))
            if count is not None:
                code = row["WijkenEnBuurten"].strip()
                crimes.setdefault(code, {})[row["SoortMisdrijf"].strip()] = count

    return {
        code: _build(code, merged, crime_year if code in crimes else None, crimes.get(code, {}))
        for code, merged in figures.items()
    }


def _build(
    buurt_code: str, figures: dict, crime_year: int | None, crimes: dict[str, int]
) -> NeighbourhoodStats:
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


def _get_rows(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> list[dict]:
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()["value"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise StatsError(f"CBS request failed ({url.split('?')[0]}): {exc}") from exc


def _get_rows_by_url(client: httpx.Client, url: str) -> list[dict]:
    """Run a query whose URL is written out by hand.

    Hand-written on purpose, so the commas inside ``startswith(...)`` and
    ``$select`` are sent as plain commas: that is the form that was checked
    against the live service. httpx's ``params`` would percent-encode them.
    """
    return _get_rows(client, f"{url}&$format=json")


def _latest_crime_period(client: httpx.Client) -> str:
    periods = _get_rows(client, f"{CRIME_PERIODS_URL}?$format=json")
    if not periods:
        raise StatsError("CBS lists no periods for the crime figures")
    return max(period["Key"].strip() for period in periods)


def _fetch_kerncijfers(buurt_code: str, client: httpx.Client) -> dict:
    """Take each column from the newest table that has a value for it."""
    figures: dict = dict.fromkeys(KERNCIJFERS_COLUMNS)
    found = False
    for url in KERNCIJFERS_URLS:
        rows = _get_rows(
            client,
            url,
            {"$filter": f"WijkenEnBuurten eq '{buurt_code}'", "$format": "json"},
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
        {"$filter": f"WijkenEnBuurten eq '{buurt_code}'", "$format": "json"},
    )
    per_year: dict[int, dict[str, int]] = {}
    for row in rows:
        count = _as_count(row.get("GeregistreerdeMisdrijven_1"))
        if count is None:
            continue
        year = int(row["Perioden"][:4])
        per_year.setdefault(year, {})[row["SoortMisdrijf"].strip()] = count

    years_with_total = [year for year, counts in per_year.items() if CRIME_TOTAL in counts]
    if not years_with_total:
        return None, {}
    latest = max(years_with_total)
    return latest, per_year[latest]


def _as_count(value: object) -> int | None:
    """Read a count that CBS sends as a number, padded text, or a blank marker."""
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _as_int(value: float | None) -> int | None:
    return None if value is None else int(value)


def _thousands(value: float | None) -> int | None:
    """CBS reports euro amounts in thousands."""
    return None if value is None else round(value * 1000)


def _share(part: float | None, total: int | None) -> float | None:
    if part is None or not total:
        return None
    return round(part / total * 100, 1)
