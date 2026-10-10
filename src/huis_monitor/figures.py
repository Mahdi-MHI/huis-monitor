"""Names and grouping of every figure a neighbourhood can be limited on."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Figure:
    """One figure: its name in criteria.toml and the label shown to people."""

    metric: str
    label: str


@dataclass(frozen=True)
class Group:
    """Figures that together describe one whole, such as all age groups."""

    title: str
    figures: tuple[Figure, ...]


# Compositions: the shares inside one group add up to (about) 100%.
GROUPS: tuple[Group, ...] = (
    Group(
        "Residents by age",
        (
            Figure("age_0_14_pct", "Ages 0 to 14"),
            Figure("age_15_24_pct", "Ages 15 to 24"),
            Figure("age_25_44_pct", "Ages 25 to 44"),
            Figure("age_45_64_pct", "Ages 45 to 64"),
            Figure("age_65_plus_pct", "Ages 65 and over"),
        ),
    ),
    Group(
        "Residents by gender",
        (
            Figure("men_pct", "Men"),
            Figure("women_pct", "Women"),
        ),
    ),
    Group(
        "Residents by marital status",
        (
            Figure("unmarried_pct", "Unmarried"),
            Figure("married_pct", "Married"),
            Figure("divorced_pct", "Divorced"),
            Figure("widowed_pct", "Widowed"),
        ),
    ),
    Group(
        "Residents by origin",
        (
            Figure("origin_nl_pct", "The Netherlands"),
            Figure("origin_europe_pct", "Rest of Europe"),
            Figure("origin_outside_europe_pct", "Outside Europe"),
        ),
    ),
    Group(
        "Households",
        (
            Figure("single_households_pct", "Single-person"),
            Figure("households_without_children_pct", "Without children"),
            Figure("households_with_children_pct", "With children"),
        ),
    ),
    Group(
        "Owner-occupied and rental homes",
        (
            Figure("owner_occupied_pct", "Owner-occupied"),
            Figure("rental_association_pct", "Rental, housing association"),
            Figure("rental_other_pct", "Rental, other landlords"),
        ),
    ),
    Group(
        "Education level",
        (
            Figure("education_basic_pct", "Basic"),
            Figure("education_secondary_pct", "Secondary"),
            Figure("education_high_pct", "High"),
        ),
    ),
)

# Registered crimes per 1,000 residents, in the order of the safety table.
CRIMES: tuple[Figure, ...] = (
    Figure("burglaries_per_1000", "Theft or burglary in home, garage, shed"),
    Figure("vehicle_thefts_per_1000", "Theft from or of motor vehicles or vessels"),
    Figure("bike_thefts_per_1000", "Theft of mopeds, scooters and bicycles"),
    Figure("pickpocketing_per_1000", "Pickpocketing"),
    Figure("traffic_accidents_per_1000", "Traffic accidents"),
    Figure("violent_crimes_per_1000", "Violence, threat, street robbery, assault"),
    Figure("arson_per_1000", "Arson"),
    Figure("drug_nuisance_per_1000", "Drug and alcohol nuisance"),
    Figure("vandalism_per_1000", "Vandalism"),
    Figure("trespassing_per_1000", "Trespassing"),
    Figure("crimes_total_per_1000", "All registered crimes"),
)

OTHER: tuple[Figure, ...] = (
    Figure("residents", "Residents"),
    Figure("density_per_km2", "Residents per km²"),
    Figure("avg_woz_eur", "Average WOZ value of homes (€)"),
    Figure("avg_income_eur", "Average income per resident (€)"),
    Figure("lowest40_income_households_pct", "Low-income households (%)"),
    Figure("urbanity", "Urbanity (1 very urban, 5 rural)"),
)

LABELS: dict[str, str] = {
    **{figure.metric: figure.label for figure in OTHER},
    **{figure.metric: f"{figure.label} per 1,000" for figure in CRIMES},
    **{
        figure.metric: f"{group.title}: {figure.label} (%)"
        for group in GROUPS
        for figure in group.figures
    },
}
