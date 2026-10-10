import httpx
import pytest

from huis_monitor.stats import StatsError, fetch_stats

BUURT = "BU05031104"

KERNCIJFERS_2025 = {
    "AantalInwoners_5": 2665,
    "Nederland_17": 1450,
    "EuropaExclusiefNederland_18": 610,
    "BuitenEuropa_19": 600,
    "Bevolkingsdichtheid_34": 14488,
    "GemiddeldeWOZWaardeVanWoningen_39": 399,
    "Koopwoningen_47": 20,
    "GemiddeldInkomenPerInwoner_78": None,
    "k_40HuishoudensMetLaagsteInkomen_84": None,
    "MateVanStedelijkheid_120": 1,
}
KERNCIJFERS_2024 = {
    **KERNCIJFERS_2025,
    "AantalInwoners_5": 2680,
    "GemiddeldInkomenPerInwoner_78": 34.3,
    "k_40HuishoudensMetLaagsteInkomen_84": 74.8,
}


def crime_row(code: str, year: int, count: int | None) -> dict:
    return {
        "SoortMisdrijf": code.ljust(6),
        "Perioden": f"{year}JJ00",
        "GeregistreerdeMisdrijven_1": count,
    }


CRIMES = [
    crime_row("0.0.0", 2024, 380),
    crime_row("0.0.0", 2025, 414),
    crime_row("1.1.1", 2025, 2),
    crime_row("1.2.3", 2025, 156),
    crime_row("1.4.1", 2025, None),
    crime_row("1.4.3", 2025, 4),
    crime_row("1.4.4", 2025, 4),
    crime_row("1.4.5", 2025, 23),
    crime_row("1.4.6", 2025, 1),
    crime_row("2.2.1", 2025, 20),
]


def make_client(kerncijfers_2025, kerncijfers_2024, crimes, status=200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["$filter"] == f"WijkenEnBuurten eq '{BUURT}'"
        path = request.url.path
        if "86165NED" in path:
            rows = kerncijfers_2025
        elif "85984NED" in path:
            rows = kerncijfers_2024
        else:
            rows = crimes
        return httpx.Response(status, json={"value": rows})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_combines_kerncijfers_and_crime_figures():
    stats = fetch_stats(BUURT, make_client([KERNCIJFERS_2025], [KERNCIJFERS_2024], CRIMES))

    assert stats.residents == 2665
    assert stats.origin_nl_pct == 54.4
    assert stats.origin_europe_pct == 22.9
    assert stats.origin_outside_europe_pct == 22.5
    assert stats.density_per_km2 == 14488
    assert stats.avg_woz_eur == 399_000
    assert stats.owner_occupied_pct == 20
    assert stats.urbanity == 1
    assert stats.crime_year == 2025
    assert stats.crimes_total == 414
    assert stats.burglaries == 2
    assert stats.violent_crimes == 32
    assert stats.vandalism == 20
    assert stats.bike_thefts == 156


def test_missing_income_is_filled_from_older_table():
    stats = fetch_stats(BUURT, make_client([KERNCIJFERS_2025], [KERNCIJFERS_2024], CRIMES))

    assert stats.avg_income_eur == 34_300
    assert stats.lowest40_income_households_pct == 74.8


def test_crime_rates_are_per_1000_residents():
    stats = fetch_stats(BUURT, make_client([KERNCIJFERS_2025], [KERNCIJFERS_2024], CRIMES))

    assert stats.per_1000(stats.crimes_total) == 155.3
    assert stats.per_1000(stats.burglaries) == 0.8
    assert stats.per_1000(None) is None


def test_buurt_without_crime_figures_gives_none():
    stats = fetch_stats(BUURT, make_client([KERNCIJFERS_2025], [KERNCIJFERS_2024], []))

    assert stats.crime_year is None
    assert stats.crimes_total is None
    assert stats.violent_crimes is None


def test_unknown_buurt_raises():
    with pytest.raises(StatsError, match="No CBS figures found"):
        fetch_stats(BUURT, make_client([], [], []))


def test_server_error_raises():
    with pytest.raises(StatsError, match="CBS request failed"):
        fetch_stats(BUURT, make_client([], [], [], status=500))
