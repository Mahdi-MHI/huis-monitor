"""Neighbourhood (buurt) statistics from CBS and police open data."""

from __future__ import annotations

from dataclasses import dataclass, field

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
COL_HOUSEHOLDS = "HuishoudensTotaal_29"
COL_EDUCATION = ("BasisonderwijsVmboMbo1_67", "HavoVwoMbo24_68", "HboWo_69")

# Shares shown as percentages: figure name -> (CBS column, what it is a share of).
# "residents", "households" and "education" mean the column holds a count that
# is divided by that total; None means CBS already publishes a percentage.
SHARE_COLUMNS: dict[str, tuple[str, str | None]] = {
    "age_0_14_pct": ("k_0Tot15Jaar_8", "residents"),
    "age_15_24_pct": ("k_15Tot25Jaar_9", "residents"),
    "age_25_44_pct": ("k_25Tot45Jaar_10", "residents"),
    "age_45_64_pct": ("k_45Tot65Jaar_11", "residents"),
    "age_65_plus_pct": ("k_65JaarOfOuder_12", "residents"),
    "men_pct": ("Mannen_6", "residents"),
    "women_pct": ("Vrouwen_7", "residents"),
    "unmarried_pct": ("Ongehuwd_13", "residents"),
    "married_pct": ("Gehuwd_14", "residents"),
    "divorced_pct": ("Gescheiden_15", "residents"),
    "widowed_pct": ("Verweduwd_16", "residents"),
    "single_households_pct": ("Eenpersoonshuishoudens_30", "households"),
    "households_without_children_pct": ("HuishoudensZonderKinderen_31", "households"),
    "households_with_children_pct": ("HuishoudensMetKinderen_32", "households"),
    "rental_association_pct": ("InBezitWoningcorporatie_49", None),
    "rental_other_pct": ("InBezitOverigeVerhuurders_50", None),
    "education_basic_pct": (COL_EDUCATION[0], "education"),
    "education_secondary_pct": (COL_EDUCATION[1], "education"),
    "education_high_pct": (COL_EDUCATION[2], "education"),
}

KERNCIJFERS_COLUMNS = tuple(
    dict.fromkeys(
        (
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
            COL_HOUSEHOLDS,
            *(column for column, _ in SHARE_COLUMNS.values()),
        )
    )
)

# Police crime codes behind each figure.
CRIME_TOTAL = "0.0.0"
# Theft or burglary in a home, garage, shed or garden house.
CRIME_BURGLARY = ("1.1.1", "1.1.2")
CRIME_BIKE_THEFT = "1.2.3"
CRIME_VANDALISM = "2.2.1"
# Sexual offence (often withheld by CBS), murder, public violence, threat,
# assault, street robbery, hold-up.
CRIME_VIOLENT = ("1.4.1", "1.4.2", "1.4.3", "1.4.4", "1.4.5", "1.4.6", "1.4.7")
OTHER_CRIMES: dict[str, tuple[str, ...]] = {
    "vehicle_thefts": ("1.2.1", "1.2.2", "1.2.5", "1.5.2"),
    "pickpocketing": ("1.2.4",),
    "traffic_accidents": ("1.3.1",),
    "arson": ("1.6.1",),
    "drug_nuisance": ("2.1.1",),
    "trespassing": ("2.4.2",),
}


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
    # Percentages by figure name (see SHARE_COLUMNS) and counts of the crime
    # types in OTHER_CRIMES. Empty when the figures were not read.
    shares: dict[str, float | None] = field(default_factory=dict)
    other_crimes: dict[str, int | None] = field(default_factory=dict)

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
    education = [figures[column] for column in COL_EDUCATION]
    totals = {
        "residents": residents,
        "households": figures[COL_HOUSEHOLDS],
        "education": None if None in education else sum(education),
    }
    shares = {}
    for name, (column, total) in SHARE_COLUMNS.items():
        value = figures[column]
        shares[name] = value if total is None else _share(value, totals[total])

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
        burglaries=_sum_crimes(crimes, CRIME_BURGLARY),
        violent_crimes=_sum_crimes(crimes, CRIME_VIOLENT),
        vandalism=crimes.get(CRIME_VANDALISM),
        bike_thefts=crimes.get(CRIME_BIKE_THEFT),
        shares=shares,
        other_crimes={name: _sum_crimes(crimes, codes) for name, codes in OTHER_CRIMES.items()},
    )


def _sum_crimes(crimes: dict[str, int], codes: tuple[str, ...]) -> int | None:
    """Add up the counts of several crime codes; ``None`` if none is published."""
    counts = [crimes[code] for code in codes if crimes.get(code) is not None]
    return sum(counts) if counts else None


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
