import pytest

from huis_monitor.geo import rd_to_wgs84

# Reference points with published coordinates in both systems.
POINTS = [
    ("Amersfoort, origin of the grid", 155_000.0, 463_000.0, 52.15517440, 5.38720621),
    ("Westertoren, Amsterdam", 120_700.723, 487_525.501, 52.37453253, 4.88352559),
    ("Martinitoren, Groningen", 233_883.131, 582_065.167, 53.21938317, 6.56820053),
]


@pytest.mark.parametrize(("name", "x", "y", "lat", "lon"), POINTS)
def test_rd_to_wgs84_matches_reference_points(name, x, y, lat, lon):
    result = rd_to_wgs84(x, y)

    assert result == pytest.approx((lat, lon), abs=1e-6)
