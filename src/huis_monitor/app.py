"""Web app: explore the neighbourhoods around a town.

Start it from the project folder with:

    streamlit run src/huis_monitor/app.py
"""

from __future__ import annotations

import html
import math
import statistics
from collections import Counter
from pathlib import Path

import httpx
import pandas as pd
import pydeck as pdk
import streamlit as st

from huis_monitor import search
from huis_monitor.areas import TIMEOUT_SECONDS, AreaError
from huis_monitor.criteria import METRICS, CriteriaError, Limit, dump_limits, load_limits
from huis_monitor.figures import CRIMES, GROUPS, LABELS, OTHER, Figure, Group
from huis_monitor.search import AreaData, Assessment
from huis_monitor.stats import StatsError

CRITERIA_FILE = Path("criteria.toml")

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
# Segment colours of the composition bars, in a fixed order, for a light and a
# dark page. Both sets were checked for colour-blind readers.
SEGMENT_COLOURS = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
}

Defaults = dict[str, dict[str, float]]


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
    return "; ".join(LABELS.get(metric, "all figures") for metric in metrics)


def default_limits() -> Defaults:
    """Limits from criteria.toml as {figure: {"min": ..., "max": ...}}."""
    if not CRITERIA_FILE.exists():
        return {}
    try:
        limits = load_limits(CRITERIA_FILE)
    except CriteriaError as exc:
        st.warning(f"{CRITERIA_FILE} was skipped: {exc}")
        return {}
    defaults: Defaults = {}
    for limit in limits:
        defaults.setdefault(limit.metric, {})[limit.kind] = limit.value
    return defaults


def values_of(area: AreaData, metric: str) -> list[float]:
    """Every published value of one figure in the area."""
    return [value for s in area.stats.values() if (value := METRICS[metric](s)) is not None]


def area_average(area: AreaData, metric: str) -> float | None:
    """Average of a percentage over the area, counting large neighbourhoods more."""
    total = weight = 0.0
    for stats in area.stats.values():
        value = METRICS[metric](stats)
        if value is not None and stats.residents:
            total += value * stats.residents
            weight += stats.residents
    return total / weight if weight else None


def page_theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # noqa: BLE001 - older Streamlit versions have no theme info
        return "light"


def composition_bar(group: Group, averages: dict[str, float]) -> str:
    """HTML for one bar split into the group's shares, with a legend below it."""
    colours = SEGMENT_COLOURS[page_theme()]
    total = sum(averages.values())
    segments = []
    legend = []
    for colour, figure in zip(colours, group.figures, strict=False):
        if figure.metric not in averages:
            continue
        share = averages[figure.metric]
        text = html.escape(f"{figure.label} {share:.0f}%")
        segments.append(
            f'<div title="{text}" style="flex:{share / total:.4f} 1 0;'
            f'background:{colour};border-radius:3px;"></div>'
        )
        legend.append(
            '<span style="white-space:nowrap;margin-right:14px;">'
            f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
            f'background:{colour};margin-right:5px;"></span>{text}</span>'
        )
    return (
        f'<div style="display:flex;gap:2px;height:26px;">{"".join(segments)}</div>'
        f'<div style="margin-top:8px;font-size:0.85rem;line-height:1.7;">{"".join(legend)}</div>'
    )


def choose_shares(area: AreaData, defaults: Defaults) -> list[Limit]:
    """Composition bars with a range slider per share; returns the chosen limits."""
    limits: list[Limit] = []
    columns = st.columns(2)
    for number, group in enumerate(GROUPS):
        averages = {
            figure.metric: average
            for figure in group.figures
            if (average := area_average(area, figure.metric)) is not None
        }
        with columns[number % 2].container(border=True):
            st.markdown(f"**{group.title}**")
            if averages:
                st.html(composition_bar(group, averages))
            else:
                st.caption("CBS publishes no figures for this group here.")
            for figure in group.figures:
                saved = defaults.get(figure.metric, {})
                low, high = st.slider(
                    f"{figure.label} (%)",
                    min_value=0,
                    max_value=100,
                    value=(int(saved.get("min", 0)), int(saved.get("max", 100))),
                    key=f"range_{figure.metric}",
                )
                if low > 0:
                    limits.append(Limit(metric=figure.metric, kind="min", value=float(low)))
                if high < 100:
                    limits.append(Limit(metric=figure.metric, kind="max", value=float(high)))
    return limits


def _summary_row(area: AreaData, figure: Figure) -> dict:
    values = values_of(area, figure.metric)
    return {
        "Figure": figure.label,
        "Lowest here": min(values) if values else None,
        "Typical here": statistics.median(values) if values else None,
        "Highest here": max(values) if values else None,
    }


def choose_in_table(
    area: AreaData, figures: tuple[Figure, ...], defaults: Defaults, kinds: dict[str, str], key: str
) -> list[Limit]:
    """A table with one row per figure and an editable column per kind of limit.

    ``kinds`` maps "min" and/or "max" to the heading of its editable column.
    """
    rows = []
    for figure in figures:
        row = _summary_row(area, figure)
        for kind, heading in kinds.items():
            row[heading] = defaults.get(figure.metric, {}).get(kind)
        rows.append(row)
    table = pd.DataFrame(rows).astype({heading: "float64" for heading in kinds.values()})

    edited = st.data_editor(
        table,
        hide_index=True,
        width="stretch",
        height=38 + 35 * len(rows),  # tall enough to show every row without scrolling
        disabled=["Figure", "Lowest here", "Typical here", "Highest here"],
        column_config={
            "Lowest here": st.column_config.NumberColumn(format="localized"),
            "Typical here": st.column_config.NumberColumn(format="localized"),
            "Highest here": st.column_config.NumberColumn(format="localized"),
            **{
                heading: st.column_config.NumberColumn(min_value=0, format="localized")
                for heading in kinds.values()
            },
        },
        key=key,
    )

    limits: list[Limit] = []
    for figure, (_, row) in zip(figures, edited.iterrows(), strict=True):
        for kind, heading in kinds.items():
            if pd.notna(row[heading]):
                limits.append(Limit(metric=figure.metric, kind=kind, value=float(row[heading])))
    return limits


def choose_limits(area: AreaData) -> list[Limit]:
    """Show every limit control and return the limits that are switched on."""
    defaults = default_limits()

    st.subheader("Residents and homes")
    st.caption(
        "Each bar shows the average of all neighbourhoods in this area. Drag the two "
        "ends of a slider to set the lowest and the highest share you accept. "
        "A slider left at 0 to 100 sets no limit."
    )
    limits = choose_shares(area, defaults)

    st.subheader("Safety")
    st.caption(
        "Registered crimes per 1,000 residents in the latest year. Type the highest "
        "number you accept in the last column; leave a cell empty for no limit."
    )
    limits += choose_in_table(area, CRIMES, defaults, {"max": "At most"}, key="crime_limits")

    st.subheader("Other figures")
    st.caption("Type a lowest and/or a highest value; leave a cell empty for no limit.")
    limits += choose_in_table(
        area, OTHER, defaults, {"min": "At least", "max": "At most"}, key="other_limits"
    )
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

    st.title(f"Neighbourhoods around {query[0]}")
    st.caption(
        f"{len(area.buurten)} neighbourhoods within {area.radius_km:g} km of {area.centre.name}. "
        "Figures: CBS and police open data. Borders: PDOK."
    )
    summary = st.container()
    limits_tab, map_tab, passed_tab, unknown_tab, rejected_tab = st.tabs(
        ["Limits", "Map", PASSED, UNKNOWN, REJECTED]
    )
    with limits_tab:
        limits = choose_limits(area)

    assessments = search.assess(area, limits)
    groups: dict[str, list[Assessment]] = {PASSED: [], UNKNOWN: [], REJECTED: []}
    for item in assessments:
        groups[status_of(item)].append(item)

    with summary:
        for column, status in zip(st.columns(3), groups, strict=True):
            column.metric(status, len(groups[status]))

    with st.sidebar:
        st.header("Your limits")
        st.caption(f"{len(limits)} limits are switched on. Changes are not saved by themselves.")
        st.download_button(
            "Download as criteria.toml",
            dump_limits(limits),
            file_name="criteria.toml",
            mime="text/plain",
            help="Put the file in the project folder to start with these limits next time.",
        )
        if st.button("Read the figures again", help="Forget the remembered data and reload."):
            read_area.clear()
            st.rerun()

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
