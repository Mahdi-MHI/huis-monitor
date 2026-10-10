# huis-monitor

Find the neighbourhoods (buurten) around a Dutch town that meet your own limits
for crime, home ownership, income and more, using open data from CBS, the police
and PDOK.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Web app

```
streamlit run src/huis_monitor/app.py
```

Choose a town and a radius and press **Load neighbourhoods**. Reading the figures
takes about a minute the first time; after that they are remembered for as long
as the app keeps running. Stop the app with Ctrl+C in the terminal.

The **Limits** tab is where you say what you accept:

- Residents and homes: a bar per topic (age, gender, marital status, origin,
  households, owner-occupied and rental homes, education) shows the average of the
  area, with a slider per share for the lowest and highest percentage you accept.
- Safety: a table of crime types where you type the highest number per 1,000
  residents you accept.
- Other figures: residents, density, WOZ value, income and urbanity.

The counts above the tabs and the **Map** change at once. **Download as
criteria.toml** in the sidebar saves the limits you have set.

## Command line

```
python -m huis_monitor address "Markt 87 Delft"   # figures for one address
python -m huis_monitor area Delft --radius 15     # neighbourhoods around a town
python -m huis_monitor find Delft --radius 15     # those that meet criteria.toml
```

## Limits

`criteria.toml` holds the starting limits, written as `min_<figure>` or
`max_<figure>`. The names of all figures are listed in
`src/huis_monitor/figures.py`. A neighbourhood that breaks no limit but lacks
data for a limited figure is listed separately instead of being rejected.

## Data

- Neighbourhood borders and address lookup: PDOK (CBS Wijken en Buurten 2025,
  Locatieserver).
- Key figures: CBS Kerncijfers wijken en buurten 2025, with missing values such
  as income filled from the 2024 table.
- Crime: registered crimes per neighbourhood per year (police data via CBS).
  Sexual offences are withheld per neighbourhood, so they are not counted.
- Education level comes from the 2024 table; CBS rounds counts to multiples of
  five, so shares in small neighbourhoods are approximate.

Figures are neighbourhood averages. Two streets in one neighbourhood can differ a
lot, so treat the result as a shortlist, not a verdict.

## Development

```
pytest
ruff check .
```
