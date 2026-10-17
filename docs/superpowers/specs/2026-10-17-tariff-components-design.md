# All-in electricity price from official tariff components

Design, 2026-10-17.

## Problem

The integration publishes the energy component only — `sensor.energie_be_electricity_price`,
currently 0.1877 €/kWh. That is between a third and a half of what a kWh actually
costs, so anyone wanting a cost figure has to supply the rest themselves.

In the installation that prompted this, the rest lives as bare numbers in a
Home Assistant template helper:

```jinja
{{ (states('sensor.daily_electricity_import') | float(0)
    * (states('sensor.energie_be_electricity_price')|float
       + 0.0117 + 0.0039 + 0.050329 + 0.002042 + 0.067)) | round(2) }}
```

Three things are wrong with that, and the third is the reason this document exists:

1. **No provenance.** The five numbers carry no source, no validity date, no unit
   convention. They came off an Energie.be tariff card months ago. Nothing says which
   card, and nothing notices when the card changes.
2. **Not shareable.** Every user of this integration who wants a cost figure retypes
   them, with their own distribution network operator's tariff and their own mistakes.
3. **It is already wrong.** The five adders are inclusive of VAT (the tariff card states
   "Alle prijzen zijn inclusief btw tenzij anders vermeld"), but the scraped energy
   component is *exclusive* of VAT — VREG's open data gives Energie.be's indexation
   formula as `0.112 × Belpex(€/MWh) + 0.80` excl. VAT, and for October 2026 that
   yields 17.71–19.22 c€/kWh, the band the website's 18.77 sits in. So the helper
   adds an excl.-VAT term to incl.-VAT terms and lands 3.5% low: 0.3227 instead of
   0.3339 €/kWh, €1.19 instead of €1.23 on a 3.689 kWh day.

A mixed VAT basis is the characteristic failure of hand-assembled tariff arithmetic:
it produces a figure that looks entirely plausible and is quietly wrong. The design
below exists to make that specific mistake structurally impossible.

## Goals

- Publish one **all-in €/kWh** sensor, so a cost template is `kWh × price` and nothing else.
- Keep every component **current without anyone retyping it**, from official sources.
- Make the VAT basis explicit at every boundary, and convert in exactly one place.
- Make staleness **loud**: a notification, never a silently old number.
- Per-user configuration (network operator, product, meter type) rather than one
  installation's constants.

## Non-goals

- **Capacity tariff / fixed costs.** The same VREG file carries the capaciteitstarief
  (60.53 €/kW/year for Fluvius West) and databeheer (18.92 €/year), and together with
  the supplier's vaste vergoeding they are of the same order as a day's variable cost.
  They are billed per kW of monthly peak, not per kWh, so they need their own entity
  and their own arithmetic. Deliberately out of scope; this design must not block it.
- **Replacing the website scrape.** VREG publishes the indexation formula and the
  monthly Belpex value, so the energy component could be computed instead of scraped.
  That needs a Belpex source of its own. Out of scope.
- **Billing accuracy.** This stays an estimate from public data, per the README.
- **Gas.** The same sources cover gas; this design is electricity only.

## Sources

All three were fetched and parsed on 2026-10-17. Values below are observed, not assumed.

### 1. VREG V-test open data (monthly, excl. VAT)

`https://assets.vlaamsenutsregulator.be/2026-10/202610-v-test-data-exclbtw%20v2_0.xlsx`
(4.0 MB). Linked from <https://www.vlaamsenutsregulator.be/cijfers/v-test-data-en-energieprijscurves>.
States "Alle prijzen zijn exclusief btw" and "De nettarieven en heffingen zijn niet
opgenomen in dit bestand".

Sheet `Var-dyn (excl. btw) (2026)`, one row per component:

| col | header | example |
| --- | --- | --- |
| 0 | Year | `2026` |
| 1 | Month | `okt` |
| 2 | Segment | `Woning` / `Onderneming` |
| 4 | Contracttype | `Afname` / `Injectie` / `Teruglevering` |
| 5 | Handelsnaam | `Energie.be` |
| 6 | Productnaam | `Elektriciteit online` |
| 7 | Variabel/Dynamisch | `Variabel` |
| 8 | **Prijsonderdeel** | `Kosten groene stroom (c€/kWh)` |
| 11 | Waarde A (€/MWh) — VNR | `150.949` |
| 12 | Waarde A (€/MWh) — last known | `164.424` |
| 25–29 | coefficients a…z | `a=0.112`, `z=0.8` |
| 30 | **Prijs** | `1.103` |

For Energie.be / Woning / Afname / `Elektriciteit online` / `Variabel` / okt 2026:

| Prijsonderdeel | value (excl. VAT) | ×1.06 | helper's hardcoded value |
| --- | --- | --- | --- |
| Kosten groene stroom (c€/kWh) | 1.103 | 1.169 | 0.0117 ✓ |
| Kosten WKK (c€/kWh) | 0.364 | 0.386 | 0.0039 ✓ |
| Vaste vergoeding (€) | 33.02 | 35.00 | — (not in the helper) |
| Enkelvoudige meter dagtarief | formula `a=0.112, z=0.8` | — | — |

Flat components carry their value in column 30; indexed ones carry coefficients and
leave 30 empty. Separate rows exist for `Tweevoudige meter dagtarief`,
`Tweevoudige meter nachttarief` and `Uitsluitend nachtmeter`, which is what makes
meter type a user choice rather than an assumption.

### 2. VREG distribution network tariffs (yearly, both VAT bases)

`https://assets.vlaamsenutsregulator.be/2025-11/Distributienettarieven%20elektriciteit%202026.xlsx`
(94 kB). Linked from <https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven>.
VREG approves these annually.

Sheet `ELEK Overzicht laagspanning` — exact cell layout:

```
row  3   cols 3..10   operator names: Fluvius Antwerpen … Fluvius Zenne-Dijle
row  4   col 0 "Exclusief btw"     col 1 "Digitale meter"   <- block header
rows 5-9 col 1 label, col 2 unit, cols 3..10 values
row 10   col 0 "Inclusief 6% btw"  col 1 "Digitale meter"   <- block header
rows 11-15 same shape
```

The file ships **both VAT bases**. Read the `Exclusief btw` block, per the single
conversion rule below; the `Inclusief 6% btw` block is then an independent oracle for
testing that conversion. Fluvius West (col 9), digital meter:

| label | unit | excl. VAT | incl. 6% | helper |
| --- | --- | --- | --- | --- |
| Totaal kWh-tarief | EUR/MWh | 63.1937 | **66.9853** | 0.067 ✓ |
| Totaal kWh-tarief — exclusief nacht | EUR/MWh | 56.5360 | 59.9282 | — |
| Capaciteitstarief — gem. maandpiek | EUR/kW/jaar | 57.0996 | 60.5255 | non-goal |
| Tarief databeheer | EUR/jaar | 17.85 | 18.92 | non-goal |

A `Klassieke meter` block follows the digital-meter blocks, and per-operator sheets
(`FW ELEK Afname`, …) carry the full tariff list.

### 3. Statutory levies (bundled table)

Not in either VREG file — the V-test file says so explicitly. Two values, from the
Energie.be tariff card ("Taksen en heffingen"):

| component | value incl. VAT |
| --- | --- |
| Bijzondere accijns op Energie | 5.0329 c€/kWh |
| Bijdrage op de Energie | 0.2042 c€/kWh |

These change by legislation, not by schedule. They ship as a table in the repository,
each entry recording the figure **as published**, the document it came from, its
`vat_basis`, and `valid_from`. The table normalises to excl. VAT when it builds
`Component`s, so the repository keeps the quotable figure and the code keeps one basis.

Whether these two are themselves incl. or excl. VAT is **open question 7** below, and
it moves the all-in price by about 0.3 c€/kWh.

### Why not the Energie.be tariff card

Everything above is also on the supplier's own monthly tariff card PDF, which would be
a single source. It was rejected:

- The tariff page does not link it. The download buttons carry no href in the
  server-rendered HTML; Angular attaches the target client-side, and the `ng-state`
  transfer block holds only translations.
- The one stable document endpoint, `…/api/v1/data/document?key=Tariffs`, redirects to
  `Februari_Tariefkaart_Energie_be…pdf`, a card from **April 2024**.
- Current cards live in a third party's S3 bucket (`dtcmedia`, carrying cards for Mega
  and others since 2021) under a monthly-changing numeric id. The bucket is publicly
  listable, so the newest card is findable, but it means depending on an aggregator
  rather than on the supplier or the regulator.
- It would add a PDF parser dependency, and a misparse writes a wrong *cost*.

VREG is a regulator publishing dated, versioned spreadsheets from a plain
server-rendered site. Compared with a supplier SPA that served the wrong page on 30–70%
of requests on the day this was written, it is the better dependency.

## Architecture

### New module: `tariffs.py`

Owns everything about cost components, the way `atrias.py` owns calorific values. It
does not know about Home Assistant entities.

```python
@dataclass(frozen=True)
class Component:
    """One priced line, always stored excl. VAT."""
    key: str                 # "network", "gsc", "wkk", "excise", "energy_levy"
    value: float             # €/kWh, excl. VAT
    source: str              # human-readable provenance
    valid_from: date
    valid_until: date | None

@dataclass(frozen=True)
class TariffComponents:
    components: tuple[Component, ...]
    vat_rate: float

    @property
    def total_excl_vat(self) -> float: ...
    @property
    def total_incl_vat(self) -> float: ...
    def newest_valid_from(self) -> date: ...
```

Four functions, each independently testable against a saved fixture:

- `parse_vtest(workbook) -> dict[str, Component]` — GSC and WKK for a given
  supplier / segment / product / meter type / month.
- `parse_network_tariffs(workbook) -> dict[str, Component]` — kWh tariff per operator.
- `STATUTORY: tuple[Component, ...]` — the bundled table.
- `read_xlsx(bytes) -> dict[str, list[list[str]]]` — a ~40-line reader over `zipfile`
  and `xml.etree`. **No new manifest requirement.** An xlsx is a zip of XML; this is
  the main reason to prefer these sources over the PDF.

### Data model

`EnergieBeData` gains one field. Existing sensors are untouched.

```python
@dataclass(frozen=True, kw_only=True)
class EnergieBeData:
    electricity: float              # unchanged: scraped, EXCL. VAT
    gas_kwh: float
    injection: float
    gas_conversion_factor: float
    gas_conversion_source: str
    tariffs: TariffComponents | None   # None when not configured
```

`electricity` keeps its current meaning and value. Renaming or re-basing it would
change an entity other people's templates already use.

### VAT, in one place

The rule is: **every value inside `tariffs.py` is excl. VAT**, and the conversion to
incl. VAT happens only in `TariffComponents.total_incl_vat`.

- Source 1 is excl. VAT — used as-is.
- Source 2 ships both; read the `Exclusief btw` block, so the conversion is not
  duplicated by the file.
- Source 3 is quoted incl. VAT on the card; divide once, at the table, and record
  `vat_basis` beside the figure.
- `vat_rate` is configurable, defaulting to 0.06. It is a statutory rate that has
  changed before.

A `Component` whose `vat_basis` cannot be established must not be published.

### Entities

| entity | unit | value |
| --- | --- | --- |
| `sensor.energie_be_all_in_electricity_price` | €/kWh | `electricity × (1+vat) + components.total_incl_vat` |

Attributes: every component with its value, `source` and `valid_from`; plus
`vat_rate`, `energy_component`, `total_components`, and `vat_basis: "incl"`.

Created only when the options needed to compute it are set. The existing five sensors
and their unique ids are unchanged.

A daily-cost sensor is intentionally *not* added: it would need a consumption entity,
which is the user's to choose. The README documents the one-line template instead.

### Configuration

Added to the existing options flow, which already builds a live dropdown from Atrias:

| option | source of choices | default |
| --- | --- | --- |
| `network_operator` | operator names from source 2 | none; required for the all-in sensor |
| `meter_kind` | `digital` / `classic` — selects the block in source 2 | `digital` |
| `tariff_scheme` | `single` / `dual_day` / `dual_night` / `night_only` — selects the row in both sources | `single` |
| `product` | product names for Energie.be from source 1 | `Elektriciteit online` |
| `vat_rate` | number | `0.06` |

`meter_kind` and `tariff_scheme` are deliberately separate: the first picks a block in
the network tariff sheet, the second picks a row in both sheets, and conflating them
would make `classic` + `night_only` unexpressible.

Reusing `_async_station_options`' pattern: build choices from the live file, and if it
cannot be fetched, keep the flow usable and say so.

### Refresh

The coordinator already ticks daily; no new schedule.

| source | real change frequency | fetch |
| --- | --- | --- |
| website energy component | monthly indexation | every tick (unchanged) |
| V-test xlsx | monthly file | conditional request, parse on change |
| network tariffs xlsx | yearly file | conditional request, parse on change |
| statutory table | legislation | no fetch |

Both VREG assets return `ETag` and `Last-Modified` (verified), so each tick sends
`If-None-Match` and parses only on a 200. Expect a handful of real parses per year
rather than 365 — and the 4 MB V-test download happens about monthly, not daily.

The asset URLs embed a dated folder and a version suffix
(`/2026-10/202610-v-test-data-exclbtw v2_0.xlsx`), so they are **discovered by scraping
the VREG page**, not constructed. The discovered URL is cached with its ETag.

### Failure handling

Today's outage taught the classification, and it carries over:

- **Network error / timeout** → `UpdateFailed(retry_after=RETRY_INTERVAL)`.
- **Asset fetched but unparseable** → non-transient. Log, and keep serving the last
  known components; do not fail the whole update, because the energy component and the
  gas sensors are independent of it.
- **No components yet and none cached** → the all-in sensor stays unavailable while the
  existing sensors keep working. Never publish a partial all-in price: a missing
  component does not make the price smaller, it makes it wrong.
- **Cookie hygiene** — the shared aiohttp session must shed affinity cookies per host
  for these fetches too, as `_async_fetch_tariff_page` already does.

### Staleness

A `homeassistant.helpers.issue_registry` repair is raised when:

- the V-test file's month is more than 2 months behind the current month, or
- the network tariff file's year is not the current year, or
- the newest `valid_from` in the statutory table is more than 18 months old.

The repair names the component, its value, and where it came from, so the fix is
either a HACS update or a corrected option — never a silent wrong number.

## Migration

The template helper becomes, with no hardcoded components:

```jinja
{{ (states('sensor.daily_electricity_import') | float(0)
    * states('sensor.energie_be_all_in_electricity_price') | float) | round(2) }}
```

Note `| float` without a default on the price, deliberately: when the price is
unavailable the cost must go unavailable too. With `| float(0)` it would silently
report a plausible, wrong, smaller number. This is how the current helper behaved
correctly during the 2026-10-17 outage, and it must be preserved.

The README documents both this template and the fact that the all-in price excludes
capacity and fixed charges, so nobody reads it as a full bill.

## Testing

TDD, fixture-driven. The spreadsheets are the interesting part, so they get real
fixtures rather than mocks — trimmed copies of the files fetched on 2026-10-17,
committed under `tests/fixtures/`.

| test | asserts |
| --- | --- |
| `read_xlsx` on both fixtures | sheet names, shared strings, cell indices |
| `parse_vtest` | GSC 1.103 and WKK 0.364 for Energie.be/Woning/okt 2026 |
| `parse_vtest` meter types | single / dual-day / dual-night / night-only pick different rows |
| `parse_network_tariffs` | Fluvius West excl. 63.1937 EUR/MWh; all 8 operators resolve |
| VAT conversion | Fluvius West total_incl == 66.9853 EUR/MWh, matching VREG's own incl. block |
| end-to-end total | 0.333933 €/kWh for the October 2026 inputs |
| regression | the five helper constants are reproduced to within rounding |
| missing component | all-in sensor unavailable, never partial |
| stale fixture | repair raised with the right component named |

The last row of the VAT test is the one that matters: VREG ships both bases for
source 2, so the implementation's conversion can be checked against the regulator's
own figure instead of against itself.

## Risks and open questions

1. **Spreadsheet layouts are not contracts.** VREG can re-shape a sheet at any release.
   Mitigation: locate cells by matching header *text* (operator name, `Prijsonderdeel`,
   `Inclusief 6% btw`), never by fixed index; fail loudly on no match; keep the last
   good values.
2. **Product naming differs between sources.** The V-test calls it
   `Elektriciteit online`; the tariff card calls it `Elektriciteit particulier online`.
   The product option must be built from the V-test file's own strings.
3. **Only Flanders.** VREG regulates Flemish operators. Brussels (Sibelga) and Wallonia
   (CWaPE/ORES) publish elsewhere. The option list is therefore Flanders-only, and the
   README must say so rather than appearing to support all of Belgium.
4. **Energie.be only.** Source 1 covers every supplier, so the parser should not
   hardcode `Energie.be` even though this integration only serves it.
5. **Is the website's energy component always the VNR-indexed value?** October's 18.77
   sits between VREG's VNR (17.71) and last-known (19.22) figures. The all-in sensor
   uses the scraped value, so this does not block the design, but a future
   scrape-free mode would have to pick a basis deliberately.
6. **Untested assumption:** that the `Klassieke meter` block repeats the digital-meter
   shape. Verify against the fixture before relying on it for `meter_kind: classic`.
7. **VAT basis of the two statutory levies — unresolved, and it matters.** The tariff
   card's blanket "Alle prijzen zijn inclusief btw tenzij anders vermeld" would make
   5.0329 and 0.2042 c€/kWh incl. VAT, and only `Bijdrage Energiefonds` is marked
   otherwise. But a statutory excise rate is normally *set* excl. VAT, with VAT levied
   on top, and secondary sources quote 5.0329 c€/kWh as the excl.-VAT rate. Both
   readings are defensible from the card alone. Impact on the all-in price:

   | reading | accijns + bijdrage incl. VAT | all-in €/kWh | 3.689 kWh |
   | --- | --- | --- | --- |
   | card is literal (already incl.) | 0.052371 | 0.333933 | €1.23 |
   | statutory (excl., add 6%) | 0.055513 | 0.337075 | €1.24 |

   Resolve before implementation, against a real invoice line or the statutory
   publication — not by picking the more convenient one. Until resolved, the table
   records the card's reading and says so in `source`, so the choice is visible in the
   sensor's attributes rather than buried.
