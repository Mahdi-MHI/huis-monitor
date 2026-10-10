from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from huis_monitor import search
from huis_monitor.areas import Buurt, Centre
from huis_monitor.search import AreaData
from huis_monitor.stats import NeighbourhoodStats

APP = str(Path(__file__).parent.parent / "src" / "huis_monitor" / "app.py")
RING = ((4.35, 52.00), (4.36, 52.00), (4.36, 52.01), (4.35, 52.01), (4.35, 52.00))


def buurt(code: str, name: str) -> Buurt:
    return Buurt(
        code=code,
        name=name,
        gemeente_code="GM0503",
        gemeente_name="Delft",
        residents=1000,
        distance_km=1.0,
        outline=(RING,),
    )


def figures(code: str, owner_occupied: float | None, burglaries: int) -> NeighbourhoodStats:
    return NeighbourhoodStats(
        buurt_code=code,
        residents=1000,
        origin_nl_pct=70.0,
        origin_europe_pct=15.0,
        origin_outside_europe_pct=15.0,
        density_per_km2=5000,
        avg_woz_eur=450_000,
        owner_occupied_pct=owner_occupied,
        avg_income_eur=40_000,
        lowest40_income_households_pct=30.0,
        urbanity=2,
        crime_year=2025,
        crimes_total=40,
        burglaries=burglaries,
        violent_crimes=5,
        vandalism=4,
        bike_thefts=6,
        shares={"men_pct": 49.0, "women_pct": 51.0, "age_0_14_pct": 20.0},
        other_crimes={"arson": 1},
    )


AREA = AreaData(
    centre=Centre("Delft, Delft, Zuid-Holland", 84_400.0, 447_500.0),
    radius_km=15.0,
    buurten=[
        buurt("BU_GOOD", "Goodbuurt"),
        buurt("BU_BAD", "Badbuurt"),
        buurt("BU_GAP", "Gapbuurt"),
    ],
    stats={
        "BU_GOOD": figures("BU_GOOD", owner_occupied=70, burglaries=1),
        "BU_BAD": figures("BU_BAD", owner_occupied=70, burglaries=9),
        "BU_GAP": figures("BU_GAP", owner_occupied=None, burglaries=1),
    },
)
CRITERIA = "[limits]\nmax_burglaries_per_1000 = 3\nmin_owner_occupied_pct = 40\n"


def start(monkeypatch, folder) -> AppTest:
    """Start the app with fake data in ``folder`` and press the load button."""
    monkeypatch.chdir(folder)
    monkeypatch.setattr(search, "load_area", lambda town, radius_km, client: AREA)
    st.cache_data.clear()  # the app remembers areas; start every test fresh
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    assert "Choose a town" in app.info[0].value
    app.sidebar.button[0].click().run()
    assert not app.exception
    return app


@pytest.fixture
def app(monkeypatch, tmp_path):
    """The loaded app, started in a folder that holds a criteria file."""
    (tmp_path / "criteria.toml").write_text(CRITERIA)
    return start(monkeypatch, tmp_path)


def counts(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def tables_with(app: AppTest, column: str) -> list:
    return [frame.value for frame in app.dataframe if column in frame.value.columns]


def test_groups_neighbourhoods_using_the_criteria_file(app):
    assert counts(app) == {"Meets every limit": "1", "Data missing": "1", "Rejected": "1"}
    passed, missing, rejected = tables_with(app, "Buurt")
    assert list(passed["Buurt"]) == ["Goodbuurt"]
    assert list(missing["No data for"]) == ["Owner-occupied and rental homes: Owner-occupied (%)"]
    assert list(rejected["Breaks limit on"]) == [
        "Theft or burglary in home, garage, shed per 1,000"
    ]
    assert tables_with(app, "Limit on")[0].to_dict("records") == [
        {"Limit on": "Theft or burglary in home, garage, shed per 1,000", "Neighbourhoods": 1}
    ]


def test_criteria_file_sets_the_starting_position_of_sliders(app):
    assert app.slider(key="range_owner_occupied_pct").value == (40, 100)
    assert app.slider(key="range_men_pct").value == (0, 100)


def test_widening_a_slider_removes_that_limit(app):
    app.slider(key="range_owner_occupied_pct").set_range(0, 100).run()

    assert not app.exception
    assert counts(app) == {"Meets every limit": "2", "Data missing": "0", "Rejected": "1"}


def test_narrowing_a_slider_rejects_neighbourhoods_outside_it(app):
    app.slider(key="range_men_pct").set_range(60, 100).run()

    assert not app.exception
    assert counts(app) == {"Meets every limit": "0", "Data missing": "0", "Rejected": "3"}


def test_without_a_criteria_file_nothing_is_limited(monkeypatch, tmp_path):
    app = start(monkeypatch, tmp_path)

    assert counts(app) == {"Meets every limit": "3", "Data missing": "0", "Rejected": "0"}
    assert app.slider(key="range_owner_occupied_pct").value == (0, 100)
