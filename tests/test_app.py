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


@pytest.fixture
def app(monkeypatch, tmp_path):
    """The app with fake data, started in a folder holding a criteria file."""
    (tmp_path / "criteria.toml").write_text(CRITERIA)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(search, "load_area", lambda town, radius_km, client: AREA)
    st.cache_data.clear()  # the app remembers areas; start every test fresh
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    return app


def load(app: AppTest) -> AppTest:
    app.sidebar.button[0].click().run()
    assert not app.exception
    return app


def counts(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def test_starts_by_asking_for_an_area(app):
    assert not app.exception
    assert "Choose a town" in app.info[0].value
    assert len(app.metric) == 0


def test_groups_neighbourhoods_using_the_criteria_file(app):
    load(app)

    assert counts(app) == {"Meets every limit": "1", "Data missing": "1", "Rejected": "1"}
    passed, missing, reasons, rejected = (frame.value for frame in app.dataframe)
    assert list(passed["Buurt"]) == ["Goodbuurt"]
    assert list(missing["No data for"]) == ["Owner-occupied homes (%)"]
    assert reasons.to_dict("records") == [
        {"Limit on": "Burglaries per 1,000 residents", "Neighbourhoods": 1}
    ]
    assert list(rejected["Breaks limit on"]) == ["Burglaries per 1,000 residents"]


def test_changing_a_limit_regroups_at_once(app):
    load(app)

    app.sidebar.number_input(key="max_burglaries_per_1000").set_value(10.0).run()

    assert not app.exception
    assert counts(app) == {"Meets every limit": "2", "Data missing": "1", "Rejected": "0"}


def test_removing_all_limits_accepts_everything(app):
    load(app)

    app.sidebar.multiselect[0].set_value([]).run()

    assert not app.exception
    assert counts(app) == {"Meets every limit": "3", "Data missing": "0", "Rejected": "0"}
