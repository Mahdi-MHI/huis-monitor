"""Convert Dutch grid coordinates (RD, in metres) to latitude and longitude."""

from __future__ import annotations

# Series approximation by Schreutelkamp and Strang van Hees; accurate to well
# under a metre inside the Netherlands, which is plenty for drawing a map.
_X0, _Y0 = 155_000.0, 463_000.0
_LAT0, _LON0 = 52.15517440, 5.38720621
_LAT_TERMS = (
    (0, 1, 3235.65389),
    (2, 0, -32.58297),
    (0, 2, -0.24750),
    (2, 1, -0.84978),
    (0, 3, -0.06550),
    (2, 2, -0.01709),
    (1, 0, -0.00738),
    (4, 0, 0.00530),
    (2, 3, -0.00039),
    (4, 1, 0.00033),
    (1, 1, -0.00012),
)
_LON_TERMS = (
    (1, 0, 5260.52916),
    (1, 1, 105.94684),
    (1, 2, 2.45656),
    (3, 0, -0.81885),
    (1, 3, 0.05594),
    (3, 1, -0.05607),
    (0, 1, 0.01199),
    (3, 2, -0.00256),
    (1, 4, 0.00128),
    (0, 2, 0.00022),
    (2, 0, -0.00022),
    (5, 0, 0.00026),
)


def rd_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Return ``(latitude, longitude)`` in degrees for an RD point."""
    dx = (x - _X0) * 1e-5
    dy = (y - _Y0) * 1e-5
    lat = _LAT0 + sum(k * dx**p * dy**q for p, q, k in _LAT_TERMS) / 3600
    lon = _LON0 + sum(k * dx**p * dy**q for p, q, k in _LON_TERMS) / 3600
    return lat, lon
