# Where New York City moves: residential turnover by neighborhood

An interactive map of residential turnover across New York City's 197 residential
neighborhoods (2020 Neighborhood Tabulation Areas). Turnover is measured as the
share of households that moved into their current home recently.

**Live:** https://joshgreenman1973.github.io/nyc-residential-turnover/

## What it shows

Four toggleable measures, all shaded darkest where turnover is highest:

| Measure | Definition | Source |
|---|---|---|
| All households | Share of all occupied homes whose householder moved in **2020 or later** (~last 5 yrs) | ACS B25038 |
| Renters | Same, restricted to **renter-occupied** homes | ACS B25038 |
| Owners | Same, restricted to **owner-occupied** homes | ACS B25038 |
| Past year | Share of residents who lived in a **different home one year earlier** | ACS B07003 |

Click any neighborhood for all four measures plus the margin of error on the
selected measure. The side panel ranks the most- and least-turnover neighborhoods.

## Headline findings (ACS 2020–2024)

- Citywide, **22.2%** of households moved in during 2020 or later. Renters churn
  far faster (**27.5%**) than owners (**11.4%**).
- **Most turnover:** Long Island City–Hunters Point (51.6%), Financial
  District–Battery Park City (46.1%), Williamsburg (45.4%), Downtown
  Brooklyn–DUMBO–Boerum Hill, Midtown South–Flatiron–Union Square — all
  rental-heavy areas, several with heavy new construction.
- **Least turnover:** Soundview–Clason Point (8.3%), Flatlands, Queens Village,
  Canarsie, South Richmond Hill — owner-heavy outer-borough neighborhoods.

## Methodology

- **Data:** U.S. Census Bureau, American Community Survey 2020–2024 5-year
  estimates, pulled at the census-tract level for the five New York City counties
  (tables B25038 and B07003).
- **Geography:** Tract estimates are summed to 2020 NTAs using the NYC Department
  of City Planning tract-to-NTA equivalency (Socrata `hm78-6dwm`). Only
  residential NTAs are shown; parks, airports, cemeteries and other
  non-residential areas are excluded. Boundaries are City Planning's
  shoreline-clipped polygons (Socrata `9nt8-h7nd`), so shading stops at the
  coastline.
- **Margins of error:** ACS figures are sample estimates. Each neighborhood rate
  carries a margin of error, computed by combining the published tract margins in
  quadrature (proportion-MOE formula). Owner-only and past-year measures, and
  small neighborhoods, have wider margins — treat small ranking differences as
  roughly equal.
- **What turnover does and does not mean:** A high rate reflects frequent moves,
  which can stem from new construction, a young renter population, or
  displacement. The map does not distinguish among those causes.

## Build

```bash
CENSUS_API_KEY=<your-free-key> python3 scripts/build_data.py
```

Writes `docs/data.geojson` (geometry + metrics) and `docs/meta.json` (citywide
context). Geometry is simplified with mapshaper (`-simplify 15% keep-shapes`) to
keep the payload small. No build-time secrets are committed; the Census key is
read from the environment.

## Files

- `scripts/build_data.py` — data pipeline (ACS pull → tract→NTA aggregation → metrics → geometry merge)
- `docs/index.html` — the map (Leaflet + CARTO basemap, single file)
- `docs/data.geojson`, `docs/meta.json` — generated data
