import json

import httpx
import pytest

from huis_monitor import export
from huis_monitor.areas import Buurt
from huis_monitor.export import average_of, export_site_data
from huis_monitor.stats import NeighbourhoodStats, StatsError

RING = ((4.35, 52.00), (4.36, 52.00), (4.36, 52.01), (4.35, 52.01), (4.35, 52.00))


def buurt(code: str, gemeente_code: str, gemeente_name: str) -> Buurt:
    return Buurt(
        code=code,
        name=f"Buurt {code}",
        gemeente_code=gemeente_code,
        gemeente_name=gemeente_name,
        residents=1000,
        distance_km=0.0,
        outline=(RING,),
        lat=52.005,
        lon=4.355,
        postcode="2628" if gemeente_code == "GM0503" else None,
    )


def figures(code: str, residents: int, burglaries: int, origin_nl: float) -> NeighbourhoodStats:
    return NeighbourhoodStats(
        buurt_code=code,
        residents=residents,
        origin_nl_pct=origin_nl,
        origin_europe_pct=None,
        origin_outside_europe_pct=None,
        density_per_km2=None,
        avg_woz_eur=None,
        owner_occupied_pct=None,
        avg_income_eur=None,
        lowest40_income_households_pct=None,
        urbanity=None,
        crime_year=2025,
        crimes_total=None,
        burglaries=burglaries,
        violent_crimes=None,
        vandalism=None,
        bike_thefts=None,
        shares={"men_pct": 50.0},
        other_crimes={"arson": 2},
    )


BUURTEN = [
    buurt("BU05030001", "GM0503", "Delft"),
    buurt("BU05030002", "GM0503", "Delft"),
    buurt("BU06030001", "GM0603", "Rijswijk (ZH.)"),
]
STATS = {
    "GM0503": {
        "BU05030001": figures("BU05030001", residents=1000, burglaries=1, origin_nl=80.0),
        "BU05030002": figures("BU05030002", residents=3000, burglaries=7, origin_nl=60.0),
    },
    "GM0603": {},
}


@pytest.fixture
def fake_sources(monkeypatch):
    monkeypatch.setattr(export, "fetch_all_buurten", lambda client: BUURTEN)
    monkeypatch.setattr(export, "latest_crime_period", lambda client: "2025JJ00")
    monkeypatch.setattr(
        export, "fetch_stats_for_gemeente", lambda code, client, period: STATS[code]
    )
    monkeypatch.setattr(export, "PAUSE_SECONDS", 0)


def read(path):
    return json.loads(path.read_text())


def test_average_counts_large_neighbourhoods_more():
    average = average_of(STATS["GM0503"].values())

    assert average["residents"] == 4000
    assert average["origin_nl_pct"] == 65.0
    assert average["burglaries_per_1000"] == 2.0
    assert "avg_woz_eur" not in average


def test_writes_one_file_per_gemeente_and_an_index(fake_sources, tmp_path):
    failed = export_site_data(tmp_path, httpx.Client())

    assert failed == []
    index = read(tmp_path / "index.json")
    assert index["crime_year"] == 2025
    assert index["complete"] is True
    assert index["average"]["residents"] == 4000
    assert [(g["code"], g["buurten"]) for g in index["gemeenten"]] == [("GM0503", 2), ("GM0603", 1)]
    assert index["gemeenten"][0]["bounds"] == [4.35, 52.0, 4.36, 52.01]
    assert index["groups"][3]["title"] == "Residents by origin"
    assert index["groups"][3]["figures"][0] == {
        "metric": "origin_nl_pct",
        "label": "The Netherlands",
    }
    assert index["crimes"][0] == {
        "metric": "burglaries_per_1000",
        "label": "Theft or burglary in home, garage, shed",
        "count": "burglaries",
    }

    delft = read(tmp_path / "gm" / "GM0503.json")
    assert delft["name"] == "Delft"
    assert delft["average"]["origin_nl_pct"] == 65.0
    first = delft["buurten"][0]
    assert first["code"] == "BU05030001"
    assert (first["lat"], first["lon"]) == (52.005, 4.355)
    assert first["outline"][0][0] == [4.35, 52.0]
    assert first["postcode"] == "2628"
    assert first["figures"]["burglaries_per_1000"] == 1.0
    assert first["figures"]["men_pct"] == 50.0
    assert first["figures"]["arson_per_1000"] == 2.0
    assert first["counts"] == {"burglaries": 1, "arson": 2}
    assert "avg_woz_eur" not in first["figures"]


def test_neighbourhood_without_figures_is_still_listed(fake_sources, tmp_path):
    export_site_data(tmp_path, httpx.Client())

    rijswijk = read(tmp_path / "gm" / "GM0603.json")
    assert rijswijk["average"] == {}
    assert "figures" not in rijswijk["buurten"][0]
    assert "postcode" not in rijswijk["buurten"][0]


def test_can_be_limited_to_some_gemeenten(fake_sources, tmp_path):
    export_site_data(tmp_path, httpx.Client(), only_gemeenten={"GM0603"})

    index = read(tmp_path / "index.json")
    assert [g["code"] for g in index["gemeenten"]] == ["GM0603"]
    assert index["complete"] is False
    assert not (tmp_path / "gm" / "GM0503.json").exists()


def test_failing_gemeente_is_reported_and_skipped(fake_sources, monkeypatch, tmp_path):
    calls: list[str] = []

    def flaky(code, client, period):
        calls.append(code)
        if code == "GM0603":
            raise StatsError("CBS is down")
        return STATS[code]

    monkeypatch.setattr(export, "fetch_stats_for_gemeente", flaky)

    failed = export_site_data(tmp_path, httpx.Client())

    assert failed == ["Rijswijk (ZH.)"]
    assert calls.count("GM0603") == export.ATTEMPTS
    index = read(tmp_path / "index.json")
    assert [g["code"] for g in index["gemeenten"]] == ["GM0503"]
    assert index["complete"] is False
