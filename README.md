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

## Website

The website in `site/` is plain HTML and JavaScript, so it can be hosted on
GitHub Pages. It has two ways in:

- **Search an area**: a town and a radius, the highest number of crimes per 1,000
  residents you accept for each type of crime, and the share of residents with
  origin the Netherlands or the rest of Europe. You get a map and a list of the
  neighbourhoods that fit. On the map, a rejected neighbourhood tells you which
  limits it breaks when you hold the mouse over it.
- **One neighbourhood**: a postcode or address shows the page of the neighbourhood
  it lies in.

Each neighbourhood page shows who lives there and what the homes are like, next to
the gemeente and the country, and a table of registered crimes.

The site reads data files that are made by Python. To try it on your own machine:

```
python -m huis_monitor export            # the whole country, takes a while
python -m http.server 8000 --directory site
```

Then open http://localhost:8000. Add `--gemeente GM0503` (repeatable) to the first
command for a quick trial with a few gemeenten.

## Command line

```
python -m huis_monitor address "Markt 87 Delft"   # figures for one address
python -m huis_monitor area Delft --radius 15     # neighbourhoods around a town
python -m huis_monitor find Delft --radius 15     # those that meet criteria.toml
python -m huis_monitor export --out site/data     # data files for the website
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
