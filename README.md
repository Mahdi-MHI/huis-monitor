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

Choose a town and a radius, press **Load neighbourhoods** and adjust the limits in
the sidebar. Reading the figures takes about a minute the first time; after that
they are remembered for as long as the app keeps running. Stop the app with
Ctrl+C in the terminal.

## Command line

```
python -m huis_monitor address "Markt 87 Delft"   # figures for one address
python -m huis_monitor area Delft --radius 15     # neighbourhoods around a town
python -m huis_monitor find Delft --radius 15     # those that meet criteria.toml
```

## Limits

`criteria.toml` holds the starting limits, written as `min_<figure>` or
`max_<figure>`. The file lists every figure that can be limited. A neighbourhood
that breaks no limit but lacks data for a limited figure is listed separately
instead of being rejected.

## Data

- Neighbourhood borders and address lookup: PDOK (CBS Wijken en Buurten 2025,
  Locatieserver).
- Key figures: CBS Kerncijfers wijken en buurten 2025, with missing values such
  as income filled from the 2024 table.
- Crime: registered crimes per neighbourhood per year (police data via CBS).

Figures are neighbourhood averages. Two streets in one neighbourhood can differ a
lot, so treat the result as a shortlist, not a verdict.

## Development

```
pytest
ruff check .
```
