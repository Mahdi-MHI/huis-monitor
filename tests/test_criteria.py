from dataclasses import replace

import pytest

from huis_monitor.criteria import CriteriaError, Limit, dump_limits, evaluate, load_limits
from huis_monitor.stats import NeighbourhoodStats

GOOD = NeighbourhoodStats(
    buurt_code="BU00000000",
    residents=1000,
    origin_nl_pct=70.0,
    origin_europe_pct=15.0,
    origin_outside_europe_pct=15.0,
    density_per_km2=5000,
    avg_woz_eur=450_000,
    owner_occupied_pct=65,
    avg_income_eur=40_000,
    lowest40_income_households_pct=30.0,
    urbanity=2,
    crime_year=2025,
    crimes_total=40,
    burglaries=2,
    violent_crimes=5,
    vandalism=4,
    bike_thefts=6,
)
LIMITS = [
    Limit(metric="burglaries_per_1000", kind="max", value=3),
    Limit(metric="owner_occupied_pct", kind="min", value=40),
]


def write(tmp_path, text: str):
    path = tmp_path / "criteria.toml"
    path.write_text(text)
    return path


def test_load_limits_reads_min_and_max(tmp_path):
    path = write(tmp_path, "[limits]\nmax_burglaries_per_1000 = 3\nmin_owner_occupied_pct = 40\n")

    assert load_limits(path) == LIMITS


def test_unknown_limit_name_is_rejected(tmp_path):
    path = write(tmp_path, "[limits]\nmax_unicorns = 3\n")

    with pytest.raises(CriteriaError, match="Unknown limit 'max_unicorns'"):
        load_limits(path)


def test_limit_must_be_a_number(tmp_path):
    path = write(tmp_path, '[limits]\nmin_residents = "many"\n')

    with pytest.raises(CriteriaError, match="must be a number"):
        load_limits(path)


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(CriteriaError, match="not found"):
        load_limits(tmp_path / "nothing.toml")


def test_neighbourhood_inside_all_limits_passes():
    verdict = evaluate(GOOD, LIMITS)

    assert verdict.passed
    assert not verdict.unknown
    assert verdict.failures == {}


def test_value_above_maximum_fails():
    verdict = evaluate(replace(GOOD, burglaries=7), LIMITS)

    assert not verdict.passed
    assert verdict.failures == {"burglaries_per_1000": "7 is above the maximum 3"}


def test_value_below_minimum_fails():
    verdict = evaluate(replace(GOOD, owner_occupied_pct=20), LIMITS)

    assert verdict.failures == {"owner_occupied_pct": "20 is below the minimum 40"}


def test_missing_figure_is_unknown_not_rejected():
    verdict = evaluate(replace(GOOD, owner_occupied_pct=None), LIMITS)

    assert verdict.failures == {}
    assert verdict.missing == ("owner_occupied_pct",)
    assert verdict.unknown
    assert not verdict.passed


def test_broken_limit_outweighs_missing_figure():
    verdict = evaluate(replace(GOOD, owner_occupied_pct=None, burglaries=7), LIMITS)

    assert not verdict.unknown
    assert not verdict.passed
    assert list(verdict.failures) == ["burglaries_per_1000"]


def test_value_equal_to_limit_passes():
    verdict = evaluate(replace(GOOD, burglaries=3, owner_occupied_pct=40), LIMITS)

    assert verdict.passed


def test_shares_and_extra_crime_types_can_be_limited():
    stats = replace(GOOD, shares={"men_pct": 49.0}, other_crimes={"arson": 3})
    limits = [
        Limit(metric="men_pct", kind="min", value=50),
        Limit(metric="arson_per_1000", kind="max", value=2),
        Limit(metric="women_pct", kind="max", value=60),
    ]

    verdict = evaluate(stats, limits)

    assert verdict.failures == {
        "men_pct": "49 is below the minimum 50",
        "arson_per_1000": "3 is above the maximum 2",
    }
    assert verdict.missing == ("women_pct",)


def test_dumped_limits_can_be_loaded_again(tmp_path):
    limits = [*LIMITS, Limit(metric="age_65_plus_pct", kind="max", value=22.5)]

    path = write(tmp_path, dump_limits(limits))

    assert load_limits(path) == limits
