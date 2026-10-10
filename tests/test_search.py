import httpx

from huis_monitor import search
from huis_monitor.areas import Buurt, Centre
from huis_monitor.criteria import Limit
from huis_monitor.search import assess_area
from huis_monitor.stats import NeighbourhoodStats


def buurt(code: str, gemeente_code: str, km: float) -> Buurt:
    return Buurt(
        code=code,
        name=f"Buurt {code}",
        gemeente_code=gemeente_code,
        gemeente_name=f"Gemeente {gemeente_code}",
        residents=1000,
        distance_km=km,
    )


def figures(code: str, owner_occupied: float) -> NeighbourhoodStats:
    return NeighbourhoodStats(
        buurt_code=code,
        residents=1000,
        origin_nl_pct=None,
        origin_europe_pct=None,
        origin_outside_europe_pct=None,
        density_per_km2=None,
        avg_woz_eur=None,
        owner_occupied_pct=owner_occupied,
        avg_income_eur=None,
        lowest40_income_households_pct=None,
        urbanity=None,
        crime_year=None,
        crimes_total=None,
        burglaries=None,
        violent_crimes=None,
        vandalism=None,
        bike_thefts=None,
    )


def test_assesses_every_buurt_and_reads_each_gemeente_once(monkeypatch):
    buurten = [
        buurt("BU_A", "GM0001", 1.0),
        buurt("BU_B", "GM0001", 2.0),
        buurt("BU_C", "GM0002", 3.0),
    ]
    per_gemeente = {
        "GM0001": {"BU_A": figures("BU_A", 60), "BU_B": figures("BU_B", 20)},
        "GM0002": {},
    }
    read: list[str] = []
    progress: list[tuple] = []

    def fake_stats(code, client):
        read.append(code)
        return per_gemeente[code]

    monkeypatch.setattr(search, "find_centre", lambda town, client: Centre(town, 0.0, 0.0))
    monkeypatch.setattr(search, "find_buurten_within", lambda centre, km, client: buurten)
    monkeypatch.setattr(search, "fetch_stats_for_gemeente", fake_stats)

    centre, assessments = assess_area(
        "Delft",
        15,
        [Limit(metric="owner_occupied_pct", kind="min", value=40)],
        httpx.Client(),
        on_progress=lambda *args: progress.append(args),
    )

    assert centre.name == "Delft"
    assert read == ["GM0001", "GM0002"]
    assert progress == [("Gemeente GM0001", 1, 2), ("Gemeente GM0002", 2, 2)]
    assert [(a.buurt.code, a.verdict.passed) for a in assessments] == [
        ("BU_A", True),
        ("BU_B", False),
        ("BU_C", False),
    ]
    assert assessments[2].stats is None
    assert assessments[2].verdict.failures == {"figures": "no data"}
