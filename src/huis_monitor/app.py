"""Web app: explore the neighbourhoods around a town.

Start it from the project folder with:

    streamlit run src/huis_monitor/app.py
"""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st

from huis_monitor import search
from huis_monitor.areas import TIMEOUT_SECONDS, AreaError
from huis_monitor.criteria import METRICS, CriteriaError, Limit, load_limits
from huis_monitor.search import AreaData, Assessment
from huis_monitor.stats import StatsError

CRITERIA_FILE = Path("criteria.toml")

LABELS = {
    "residents": "Residents",
    "origin_nl_pct": "Origin Netherlands (%)",
    "origin_europe_pct": "Origin rest of Europe (%)",
    "origin_outside_europe_pct": "Origin outside Europe (%)",
    "density_per_km2": "Residents per km²",
    "avg_woz_eur": "Average WOZ value (€)",
    "owner_occupied_pct": "Owner-occupied homes (%)",
    "avg_income_eur": "Income per resident (€)",
    "lowest40_income_households_pct": "Low-income households (%)",
    "urbanity": "Urbanity (1 very urban, 5 rural)",
    "crimes_total_per_1000": "All crimes per 1,000 residents",
    "burglaries_per_1000": "Burglaries per 1,000 residents",
    "violent_crimes_per_1000": "Violent crimes per 1,000 residents",
    "vandalism_per_1000": "Vandalism per 1,000 residents",
    "bike_thefts_per_1000": "Bike thefts per 1,000 residents",
}

PASSED = "Meets every limit"
UNKNOWN = "Data missing"
REJECTED = "Rejected"
# Map fill per status as red, green, blue, opacity. The status is also written
# in the tooltip and in the tables, so colour is never the only signal.
FILL = {
    PASSED: [12, 163, 12, 170],
    UNKNOWN: [250, 178, 25, 170],
    REJECTED: [143, 143, 138, 50],
}


@st.cache_data(ttl="12h", show_spinner=False)
def read_area(town: str, radius_km: float) -> AreaData:
    """Read an area once and remember it while the app keeps running."""
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        return search.load_area(town, radius_km, client)


def status_of(item: Assessment) -> str:
    if item.verdict.passed:
        return PASSED
    return UNKNOWN if item.verdict.unknown else REJECTED


def label_list(metrics) -> str:
    return ", ".join(LABELS.get(metric, "all figures") for metric in metrics)


def default_limits() -> dict[str, dict[str, float]]:
    """Limits from criteria.toml as {figure: {"min": ..., "max": ...}}."""
    if not CRITERIA_FILE.exists():
        return {}
    try:
        limits = load_limits(CRITERIA_FILE)
    except CriteriaError as exc:
        st.sidebar.warning(f"{CRITERIA_FILE} was skipped: {exc}")
        return {}
    defaults: dict[str, dict[str, float]] = {}
    for limit in limits:
        defaults.setdefault(limit.metric, {})[limit.kind] = limit.value
    return defaults


def choose_limits(area: AreaData) -> list[Limit]:
    """Show the limit controls in the sidebar and return the chosen limits."""
    defaults = default_limits()
    st.header("Limits")
    chosen = st.multiselect(
        "Figures to limit",
        options=list(METRICS),
        default=list(defaults),
        format_func=LABELS.get,
        help="Starts with the limits from criteria.toml. Changes here are not saved.",
    )

    limits: list[Limit] = []
    for metric in chosen:
        values = [value for s in area.stats.values() if (value := METRICS[metric](s)) is not None]
        st.markdown(f"**{LABELS[metric]}**")
        if values:
            st.caption(f"In this area: {min(values):,g} to {max(values):,g}")
        low_column, high_column = st.columns(2)
        low = low_column.number_input(
            "At least",
            value=defaults.get(metric, {}).get("min"),
            step=1.0,
            format="%g",
            placeholder="no minimum",
            key=f"min_{metric}",
        )
        high = high_column.number_input(
            "At most",
            value=defaults.get(metric, {}).get("max"),
            step=1.0,
            format="%g",
            placeholder="no maximum",
            key=f"max_{metric}",
        )
        if low is not None:
            limits.append(Limit(metric=metric, kind="min", value=float(low)))
        if high is not None:
            limits.append(Limit(metric=metric, kind="max", value=float(high)))
    return limits


def to_table(items: list[Assessment]) -> pd.DataFrame:
    rows = []
    for item in items:
        row = {
            "Buurt": item.buurt.name,
            "Gemeente": item.buurt.gemeente_name,
            "Km": item.buurt.distance_km,
        }
        if item.verdict.failures:
            row["Breaks limit on"] = label_list(item.verdict.failures)
        if item.verdict.missing:
            row["No data for"] = label_list(item.verdict.missing)
        for metric, label in LABELS.items():
            row[label] = None if item.stats is None else METRICS[metric](item.stats)
        row["Code"] = item.buurt.code
        rows.append(row)
    return pd.DataFrame(rows)


def show_table(items: list[Assessment], file_name: str) -> None:
    if not items:
        st.info("No neighbourhoods in this group.")
        return
    table = to_table(items)
    st.dataframe(table, hide_index=True, width="stretch")
    st.download_button(
        "Download as CSV",
        table.to_csv(index=False),
        file_name=file_name,
        mime="text/csv",
    )


def _figure(stats, metric: str, pattern: str = "{:g}") -> str:
    value = METRICS[metric](stats)
    return "n/a" if value is None else pattern.format(value)


def tooltip_lines(item: Assessment) -> dict[str, str]:
    """Text for the map tooltip, one entry per line (values are shown as plain text)."""
    lines = {"crime": "No figures published", "homes": "", "value": "", "breaks": "", "gaps": ""}
    stats = item.stats
    if stats is not None:
        burglaries = _figure(stats, "burglaries_per_1000")
        violence = _figure(stats, "violent_crimes_per_1000")
        owner_occupied = _figure(stats, "owner_occupied_pct", "{:g}%")
        low_income = _figure(stats, "lowest40_income_households_pct", "{:g}%")
        woz = _figure(stats, "avg_woz_eur", "€ {:,}")
        residents = _figure(stats, "residents", "{:,}")
        lines["crime"] = f"Per 1,000 residents: burglaries {burglaries}, violence {violence}"
        lines["homes"] = f"Owner-occupied {owner_occupied}, low-income households {low_income}"
        lines["value"] = f"Average WOZ {woz}, residents {residents}"
    if item.verdict.failures:
        lines["breaks"] = f"Breaks limit on: {label_list(item.verdict.failures)}"
    if item.verdict.missing:
        lines["gaps"] = f"No data for: {label_list(item.verdict.missing)}"
    return lines


def show_map(area: AreaData, assessments: list[Assessment]) -> None:
    order = {REJECTED: 0, UNKNOWN: 1, PASSED: 2}
    features = []
    for item in sorted(assessments, key=lambda item: order[status_of(item)]):
        if not item.buurt.outline:
            continue
        status = status_of(item)
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[list(point) for point in ring]] for ring in item.buurt.outline
                    ],
                },
                "properties": {
                    "name": item.buurt.name,
                    "place": f"{item.buurt.gemeente_name} · {item.buurt.distance_km:g} km",
                    "status": status,
                    "fill": FILL[status],
                    **tooltip_lines(item),
                },
            }
        )

    latitude, longitude = area.centre.lat_lon
    deck = pdk.Deck(
        layers=[
            pdk.Layer(
                "GeoJsonLayer",
                {"type": "FeatureCollection", "features": features},
                pickable=True,
                auto_highlight=True,
                get_fill_color="properties.fill",
                get_line_color=[70, 70, 70, 140],
                line_width_min_pixels=1,
            )
        ],
        initial_view_state=pdk.ViewState(
            latitude=latitude,
            longitude=longitude,
            zoom=13.9 - math.log2(area.radius_km),
        ),
        map_style=None,
        tooltip={
            "html": "<b>{name}</b><br/>{place}<br/><b>{status}</b><br/>"
            "{crime}<br/>{homes}<br/>{value}<br/>{breaks}<br/>{gaps}"
        },
    )
    st.caption(
        "Green: meets every limit. Amber: breaks no limit, but data is missing. "
        "Grey: rejected. Hover over a neighbourhood for its figures."
    )
    # Streamlit 1.65 draws the hover box one map-height too high; anchoring the
    # box's container to the top of the map puts it back under the pointer.
    st.html("<style>.deck-widgets-root { position: absolute; top: 0; left: 0; }</style>")
    st.pydeck_chart(deck, height=620)


def main() -> None:
    st.set_page_config(page_title="Huis monitor", layout="wide")

    with st.sidebar:
        st.header("Area")
        with st.form("area"):
            town = st.text_input("Town", value="Delft")
            radius = st.slider("Radius (km)", min_value=1, max_value=30, value=15)
            if st.form_submit_button("Load neighbourhoods", type="primary"):
                st.session_state["query"] = (town.strip(), float(radius))

    query = st.session_state.get("query")
    if query is None:
        st.title("Huis monitor")
        st.info("Choose a town and a radius on the left, then press Load neighbourhoods.")
        return

    try:
        with st.spinner("Reading the figures. The first time takes about a minute."):
            area = read_area(*query)
    except (AreaError, StatsError) as exc:
        st.error(str(exc))
        return

    with st.sidebar:
        limits = choose_limits(area)
        if st.button("Read the figures again", help="Forget the remembered data and reload."):
            read_area.clear()
            st.rerun()

    assessments = search.assess(area, limits)
    groups: dict[str, list[Assessment]] = {PASSED: [], UNKNOWN: [], REJECTED: []}
    for item in assessments:
        groups[status_of(item)].append(item)

    st.title(f"Neighbourhoods around {query[0]}")
    st.caption(
        f"{len(assessments)} neighbourhoods within {area.radius_km:g} km of {area.centre.name}. "
        "Figures: CBS and police open data. Borders: PDOK."
    )
    for column, status in zip(st.columns(3), groups, strict=True):
        column.metric(status, len(groups[status]))

    map_tab, passed_tab, unknown_tab, rejected_tab = st.tabs(
        ["Map", PASSED, UNKNOWN, REJECTED]
    )
    with map_tab:
        show_map(area, assessments)
    with passed_tab:
        show_table(groups[PASSED], "neighbourhoods-meeting-limits.csv")
    with unknown_tab:
        st.caption("These break no limit, but CBS has not published every figure you limit.")
        show_table(groups[UNKNOWN], "neighbourhoods-data-missing.csv")
    with rejected_tab:
        reasons = Counter(metric for item in groups[REJECTED] for metric in item.verdict.failures)
        if reasons:
            st.caption("How many neighbourhoods break each limit (one can break several).")
            st.dataframe(
                pd.DataFrame(
                    [(LABELS[metric], count) for metric, count in reasons.most_common()],
                    columns=["Limit on", "Neighbourhoods"],
                ),
                hide_index=True,
            )
        show_table(groups[REJECTED], "neighbourhoods-rejected.csv")


main()
