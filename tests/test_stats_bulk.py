import httpx
import pytest

from huis_monitor import stats
from huis_monitor.stats import StatsError, fetch_stats_for_gemeente


def kerncijfers(code: str, residents: int, income: float | None = None) -> dict:
    return {
        "WijkenEnBuurten": code,
        "AantalInwoners_5": residents,
        "Nederland_17": residents // 2,
        "EuropaExclusiefNederland_18": residents // 4,
        "BuitenEuropa_19": residents // 4,
        "Bevolkingsdichtheid_34": 5000,
        "GemiddeldeWOZWaardeVanWoningen_39": 400,
        "Koopwoningen_47": 60,
        "GemiddeldInkomenPerInwoner_78": income,
        "k_40HuishoudensMetLaagsteInkomen_84": None if income is None else 35.0,
        "MateVanStedelijkheid_120": 2,
    }


def crime(code: str, crime_code: str, count: str) -> dict:
    """Rows of the bulk table hold padded text, like the real service."""
    return {
        "WijkenEnBuurten": code,
        "SoortMisdrijf": crime_code.ljust(6),
        "Perioden": "2025JJ00",
        "GeregistreerdeMisdrijven_1": count,
    }


TABLE_2025 = [kerncijfers("BU05031104", 2000), kerncijfers("BU05031105", 1000)]
TABLE_2024 = [kerncijfers("BU05031104", 1900, income=34.3)]
CRIMES = [
    crime("BU05031104", "0.0.0", "     414"),
    crime("BU05031104", "1.1.1", "       2"),
    crime("BU05031104", "1.4.5", "      23"),
    crime("BU05031104", "1.4.1", "       ."),
]
PERIODS = [{"Key": "2024JJ00"}, {"Key": "2025JJ00"}]


def make_client(crimes=CRIMES, seen: list | None = None, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.query.decode()
        if seen is not None:
            seen.append(f"{request.url.path}?{query}")
        path = request.url.path
        if path.endswith("/Perioden"):
            rows = PERIODS
        elif "86165NED" in path:
            rows = TABLE_2025
        elif "85984NED" in path:
            rows = TABLE_2024
        else:
            rows = [row for row in crimes if f"'{row['WijkenEnBuurten'][:8]}" in query] or [
                row for row in crimes if "'BU0503')" in query
            ]
        return httpx.Response(status, json={"value": rows})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_stats_for_every_buurt_in_the_gemeente():
    result = fetch_stats_for_gemeente("GM0503", make_client())

    assert sorted(result) == ["BU05031104", "BU05031105"]
    centrum = result["BU05031104"]
    assert centrum.residents == 2000
    assert centrum.avg_woz_eur == 400_000
    assert centrum.crime_year == 2025
    assert centrum.crimes_total == 414
    assert centrum.burglaries == 2
    assert centrum.violent_crimes == 23


def test_income_comes_from_the_older_table_when_missing():
    result = fetch_stats_for_gemeente("0503", make_client())

    assert result["BU05031104"].avg_income_eur == 34_300
    assert result["BU05031105"].avg_income_eur is None


def test_buurt_without_crime_rows_has_no_crime_figures():
    result = fetch_stats_for_gemeente("GM0503", make_client())

    assert result["BU05031105"].crime_year is None
    assert result["BU05031105"].crimes_total is None


def test_queries_are_sent_with_plain_commas_and_latest_period():
    seen: list = []

    fetch_stats_for_gemeente("GM0503", make_client(seen=seen))

    crime_query = next(url for url in seen if "UntypedDataSet" in url)
    assert "startswith(WijkenEnBuurten,'BU0503')" in crime_query
    assert "Perioden%20eq%20'2025JJ00'" in crime_query
    assert "$select=WijkenEnBuurten,SoortMisdrijf,Perioden," in crime_query


def test_large_gemeente_is_read_wijk_by_wijk(monkeypatch):
    monkeypatch.setattr(stats, "MAX_ROWS_PER_REQUEST", 100)  # 2 buurten x 59 rows > 100
    seen: list = []

    result = fetch_stats_for_gemeente("GM0503", make_client(seen=seen))

    crime_queries = [url for url in seen if "UntypedDataSet" in url]
    assert len(crime_queries) == 1  # both buurten are in wijk BU050311
    assert "startswith(WijkenEnBuurten,'BU050311')" in crime_queries[0]
    assert result["BU05031104"].violent_crimes == 23


def test_server_error_raises():
    with pytest.raises(StatsError, match="CBS request failed"):
        fetch_stats_for_gemeente("GM0503", make_client(status=500))


def test_shares_and_other_crime_types_are_filled_in():
    row = {
        **kerncijfers("BU05031104", 2000),
        "Mannen_6": 1100,
        "Vrouwen_7": 900,
        "k_65JaarOfOuder_12": 300,
        "HuishoudensTotaal_29": 1000,
        "Eenpersoonshuishoudens_30": 550,
        "InBezitWoningcorporatie_49": 26,
        "BasisonderwijsVmboMbo1_67": None,
        "HavoVwoMbo24_68": None,
        "HboWo_69": None,
    }
    older = {
        **kerncijfers("BU05031104", 1900, income=34.3),
        "BasisonderwijsVmboMbo1_67": 200,
        "HavoVwoMbo24_68": 300,
        "HboWo_69": 500,
    }
    crimes = [
        crime("BU05031104", "1.1.1", "       2"),
        crime("BU05031104", "1.1.2", "       1"),
        crime("BU05031104", "1.2.1", "       5"),
        crime("BU05031104", "1.2.5", "       4"),
        crime("BU05031104", "1.6.1", "       0"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/Perioden"):
            rows = PERIODS
        elif "86165NED" in path:
            rows = [row]
        elif "85984NED" in path:
            rows = [older]
        else:
            rows = crimes
        return httpx.Response(200, json={"value": rows})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    centrum = fetch_stats_for_gemeente("GM0503", client)["BU05031104"]

    assert centrum.shares["men_pct"] == 55.0
    assert centrum.shares["age_65_plus_pct"] == 15.0
    assert centrum.shares["single_households_pct"] == 55.0
    assert centrum.shares["rental_association_pct"] == 26
    assert centrum.shares["education_high_pct"] == 50.0
    assert centrum.shares["married_pct"] is None
    assert centrum.burglaries == 3  # home plus garage or shed
    assert centrum.other_crimes["vehicle_thefts"] == 9
    assert centrum.other_crimes["arson"] == 0
    assert centrum.other_crimes["pickpocketing"] is None
