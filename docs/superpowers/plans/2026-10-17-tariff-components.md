# All-in Electricity Price Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish one `sensor.energie_be_all_in_electricity_price` built from official VREG tariff components, so a cost template is `kWh × price` and no component is ever retyped by hand.

**Architecture:** Two new dependency-free modules do all the work and know nothing about Home Assistant — `xlsx.py` reads a workbook out of a zip of XML, and `tariffs.py` holds the component model, the two spreadsheet parsers, the statutory table and the staleness rules. A third, `vreg.py`, discovers and conditionally fetches the two VREG assets. The coordinator gains one field and about fifteen lines of delegation; the sensor platform gains one entity.

**Tech Stack:** Python 3.13 on Home Assistant 2026.3+; stdlib `zipfile` + `xml.etree` for the spreadsheets; `aiohttp` through HA's shared session; `unittest` for tests. No new entry in `manifest.json` `requirements`.

**Spec:** `docs/superpowers/specs/2026-10-17-tariff-components-design.md`

## Global Constraints

- **No new dependency.** `manifest.json` `requirements` stays exactly `["beautifulsoup4==4.13.3"]`. If a task seems to need openpyxl, pandas or a PDF parser, the task is wrong.
- **Every value inside `tariffs.py` is excl. VAT.** The only multiplication by `(1 + vat_rate)` in the whole codebase lives in `TariffComponents`. No literal `1.06` anywhere else.
- **A component whose VAT basis cannot be established must not be published.**
- **Locate cells by matching header text, never by fixed row or column index.** Verified reason: the same sheet yields `Exclusief btw` at row index 7 with one reader and 4 with another, depending only on whether blank rows are kept. Match the text.
- **Normalise whitespace before matching or displaying any spreadsheet string.** Verified: operator names contain embedded newlines (`'Fluvius\nAntwerpen'`, `'Fluvius \nHalle-Vilvoorde'`), units carry trailing spaces (`'EUR/jaar '`), supplier names too (`'Aspiravi Energy '`).
- **The five existing sensors, their unique ids and their values do not change.** `EnergieBeData.electricity` keeps meaning scraped energy component, excl. VAT.
- **Tests run with no pytest and no pip:** `python3 -m unittest discover -s tests -v`, on Python 3.11 or newer, with Home Assistant *not* installed. Therefore `xlsx.py`, `tariffs.py` and `vreg.py` must not import `homeassistant`, must not use PEP 695 `type` aliases, and must not import `.coordinator`.
- **Flanders only.** The operator list comes from a VREG file that covers Flemish operators; the README must say so.
- **Do not hardcode `Energie.be`** in a parser. The supplier is an argument.

## Review Focus

Five things the spec implies, that a reasonable user will hit, and that no task's happy path would catch. Each one's test is already placed in the task that owns the code.

1. **Whitespace inside spreadsheet strings** — `'Fluvius\nAntwerpen'` must select the same operator a user picked as `Fluvius Antwerpen`; a trailing space must not make a supplier unfindable. (Task 3, Task 4)
2. **A month the file does not carry yet** — in early November the October file is still the newest published; asking for November must fall back to the newest month present and say so in `source`, not raise and not return nothing. (Task 4)
3. **A `vat_rate` other than 0.06** — the rate has changed before; with `vat_rate=0.0` the all-in price must equal the excl.-VAT sum exactly, which fails if any `1.06` is baked in. (Task 2)
4. **A value that will not parse, or parses outside a plausible band** — a reshaped sheet can put `Maximumtarief` (327.6 EUR/MWh, five times the real tariff) where `Totaal kWh-tarief` was. Refuse the component; never publish it. (Task 3, Task 6)
5. **One component missing while the others parse** — the all-in price must go unavailable, because a missing component does not make the price smaller, it makes it wrong. (Task 6)

---

## File Structure

| file | responsibility |
| --- | --- |
| `custom_components/energiebe/xlsx.py` | **new.** Read a `.xlsx` into `{sheet name: rows}`. Nothing domain-specific. |
| `custom_components/energiebe/tariffs.py` | **new.** `Component`, `TariffComponents`, `parse_network_tariffs`, `parse_vtest`, `STATUTORY`, `build`, `stale_reasons`. No I/O, no HA. |
| `custom_components/energiebe/vreg.py` | **new.** Discover the two asset URLs on the VREG site and fetch them conditionally (ETag). |
| `custom_components/energiebe/const.py` | modify. Config keys, defaults, VREG page URLs, staleness thresholds. |
| `custom_components/energiebe/coordinator.py` | modify. One new field on `EnergieBeData`; delegate to `vreg`/`tariffs`; cache last known. |
| `custom_components/energiebe/sensor.py` | modify. One new entity class. |
| `custom_components/energiebe/config_flow.py` | modify. Five new options with live choices. |
| `custom_components/energiebe/strings.json`, `translations/en.json` | modify. Labels for the new options and the staleness repair. |
| `tests/loader.py` | **new.** Imports the modules under test without Home Assistant installed. |
| `tests/test_xlsx.py`, `tests/test_tariffs_model.py`, `tests/test_network_tariffs.py`, `tests/test_vtest.py`, `tests/test_statutory.py`, `tests/test_build.py`, `tests/test_vreg.py` | **new.** One file per unit. |
| `tests/fixtures/nettarieven-2026.xlsx`, `tests/fixtures/vtest-202610.xlsx`, `tests/fixtures/vreg-vtest-page.html`, `tests/fixtures/vreg-nettarieven-page.html` | **new.** Real files, fetched 2026-10-17. |
| `tools/trim_vtest.py` | **new.** Builds the trimmed V-test fixture from a full download, so the fixture can be refreshed next year. |

Tasks 1–7 are fully testable locally. Tasks 8–11 touch Home Assistant APIs that cannot be imported here; they are deliberately thin, and each carries its own live-verification step against a running instance.

---

### Task 1: XLSX reader, test harness, and the network-tariff fixture

**Files:**
- Create: `custom_components/energiebe/xlsx.py`
- Create: `tests/loader.py`
- Create: `tests/test_xlsx.py`
- Create: `tests/fixtures/nettarieven-2026.xlsx` (downloaded, committed whole — 94 kB)

**Interfaces:**
- Consumes: nothing.
- Produces: `read_xlsx(data: bytes) -> dict[str, list[list[str]]]`, `XlsxError`; and `tests/loader.py`'s `load(name: str) -> ModuleType`.

- [ ] **Step 1: Download the fixture**

```bash
mkdir -p tests/fixtures tools
curl -sSL -o tests/fixtures/nettarieven-2026.xlsx \
  'https://assets.vlaamsenutsregulator.be/2025-11/Distributienettarieven%20elektriciteit%202026.xlsx'
python3 -c "import zipfile;print(len(zipfile.ZipFile('tests/fixtures/nettarieven-2026.xlsx').namelist()),'parts')"
```

Expected: `43 parts`. If the download 404s, the 2026 file has been superseded; take the current year's file from <https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven> and update the expected values in Task 3 from it, recording what changed.

- [ ] **Step 2: Write the loader**

Home Assistant is not installed here, and `custom_components/energiebe/__init__.py` imports it. Loading a module by file path under a synthetic parent package keeps relative imports working without ever executing that `__init__.py`.

```python
"""Import the Home-Assistant-free modules under test without Home Assistant.

``custom_components.energiebe.__init__`` imports ``homeassistant``, which is not
installed in a plain checkout, and ``coordinator`` uses syntax newer than the
Python this may run on. So register a stand-in parent package whose ``__path__``
points at the real directory and load single modules into it: relative imports
between them resolve, and the package body never runs.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from typing import Any

PACKAGE = "energiebe_under_test"
ROOT = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "energiebe"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def _parent() -> types.ModuleType:
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT)]
        sys.modules[PACKAGE] = package
    return sys.modules[PACKAGE]


def load(name: str) -> Any:
    """Return the integration module ``name``, loaded from its file."""
    _parent()
    full = f"{PACKAGE}.{name}"
    if full in sys.modules:
        return sys.modules[full]
    spec = importlib.util.spec_from_file_location(full, ROOT / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {name} from {ROOT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)
    return module


def fixture(name: str) -> bytes:
    """Return the bytes of a committed fixture."""
    return (FIXTURES / name).read_bytes()
```

- [ ] **Step 3: Write the failing test**

```python
"""The xlsx reader, against a real VREG workbook."""

import unittest

from loader import fixture, load

xlsx = load("xlsx")


class TestReadXlsx(unittest.TestCase):
    def setUp(self) -> None:
        self.sheets = xlsx.read_xlsx(fixture("nettarieven-2026.xlsx"))

    def test_sheet_names_in_workbook_order(self) -> None:
        names = list(self.sheets)
        self.assertEqual(names[0], "ELEK Overzicht laagspanning")
        self.assertIn("FW ELEK Afname", names)
        self.assertEqual(len(names), 18)

    def test_shared_strings_are_resolved(self) -> None:
        rows = self.sheets["ELEK Overzicht laagspanning"]
        labels = [row[1] for row in rows if len(row) > 1]
        self.assertIn("Totaal kWh-tarief", labels)
        self.assertIn("Digitale meter", labels)

    def test_numbers_come_back_as_written(self) -> None:
        rows = self.sheets["ELEK Overzicht laagspanning"]
        row = next(r for r in rows if len(r) > 2 and r[1] == "Totaal kWh-tarief")
        self.assertAlmostEqual(float(row[9]), 63.1937, places=4)

    def test_blank_rows_are_kept_as_empty_lists(self) -> None:
        # Row numbering is not preserved across readers, which is exactly why
        # parsers must match header text -- but a blank row must not shift the
        # columns of the rows around it either.
        rows = self.sheets["ELEK Overzicht laagspanning"]
        self.assertIn([], rows)

    def test_two_letter_columns(self) -> None:
        # The V-test sheet runs out to column AE; a reader that only handles
        # single letters silently drops the price column.
        self.assertEqual(xlsx._column("AE17"), 30)
        self.assertEqual(xlsx._column("A1"), 0)
        self.assertEqual(xlsx._column("Z9"), 25)

    def test_rubbish_input_raises(self) -> None:
        with self.assertRaises(xlsx.XlsxError):
            xlsx.read_xlsx(b"this is not a zip")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run it to make sure it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError`/`ImportError` for `xlsx`.

- [ ] **Step 5: Write the reader**

```python
"""Read a .xlsx without openpyxl.

An xlsx is a zip of XML: the workbook names its sheets, a relationship file says
which part each one lives in, strings are pooled in ``sharedStrings.xml`` and
numbers are stored as text. That is the whole format as far as reading a table
of values goes, so the integration can read regulator spreadsheets without
taking on a spreadsheet library.

Values come back as the strings the file holds. Callers know which of their own
columns are numbers, and the files mix both in one column.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class XlsxError(Exception):
    """Raised when a workbook is not one we can read."""


def _column(ref: str) -> int:
    """Turn a cell reference such as "AE17" into a zero-based column index."""
    number = 0
    for char in ref:
        if not char.isalpha():
            break
        number = number * 26 + (ord(char.upper()) - 64)
    return number - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(text.text or "" for text in item.iter(f"{_MAIN}t"))
        for item in root.iter(f"{_MAIN}si")
    ]


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        node = cell.find(f"{_MAIN}is")
        if node is None:
            return ""
        return "".join(text.text or "" for text in node.iter(f"{_MAIN}t"))
    value = cell.find(f"{_MAIN}v")
    if value is None or value.text is None:
        return ""
    if cell.get("t") == "s":
        index = int(value.text)
        return shared[index] if index < len(shared) else ""
    return value.text


def _rows(data: bytes, shared: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in ET.fromstring(data).iter(f"{_MAIN}row"):
        cells: dict[int, str] = {}
        for cell in row.iter(f"{_MAIN}c"):
            text = _cell_text(cell, shared)
            if text != "":
                cells[_column(cell.get("r") or "")] = text
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    return rows


def read_xlsx(data: bytes) -> dict[str, list[list[str]]]:
    """Return ``{sheet name: rows}`` in the order the workbook lists its sheets."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        shared = _shared_strings(archive)
        targets = {
            rel.get("Id"): (rel.get("Target") or "").lstrip("/")
            for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        sheets: dict[str, list[list[str]]] = {}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).iter(f"{_MAIN}sheet"):
            target = targets[sheet.get(f"{_REL}id")]
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            sheets[sheet.get("name") or ""] = _rows(archive.read(target), shared)
        return sheets
    except (KeyError, OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as err:
        raise XlsxError(f"Not a readable xlsx: {err}") from err
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 6 tests, PASS.

- [ ] **Step 7: Commit**

```bash
git add custom_components/energiebe/xlsx.py tests/loader.py tests/test_xlsx.py tests/fixtures/nettarieven-2026.xlsx
git commit -m "feat: read xlsx workbooks without a spreadsheet dependency"
```

---

### Task 2: The component model, and VAT in exactly one place

**Files:**
- Create: `custom_components/energiebe/tariffs.py`
- Create: `tests/test_tariffs_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Component(key, value, source, valid_from, valid_until=None)`; `TariffComponents(components, vat_rate=DEFAULT_VAT_RATE)` with `total_excl_vat`, `total_incl_vat`, `newest_valid_from`, `keys()`, `all_in_price(energy_excl_vat)`, `as_attributes()`; `DEFAULT_VAT_RATE = 0.06`; `TariffError`.

- [ ] **Step 1: Write the failing test**

```python
"""The component model: one VAT conversion, and it is here."""

import unittest
from datetime import date

from loader import load

tariffs = load("tariffs")


def component(key: str, value: float, year: int = 2026) -> object:
    return tariffs.Component(
        key=key, value=value, source=f"test {key}", valid_from=date(year, 1, 1)
    )


class TestTariffComponents(unittest.TestCase):
    def setUp(self) -> None:
        self.components = tariffs.TariffComponents(
            components=(component("network", 0.0631937), component("gsc", 0.01103)),
            vat_rate=0.06,
        )

    def test_total_excl_vat_is_the_plain_sum(self) -> None:
        self.assertAlmostEqual(self.components.total_excl_vat, 0.0742237, places=9)

    def test_total_incl_vat_applies_the_rate_once(self) -> None:
        self.assertAlmostEqual(self.components.total_incl_vat, 0.078677122, places=9)

    def test_all_in_price_includes_the_energy_component(self) -> None:
        # 0.1877 scraped, excl. VAT, plus these two components, all taxed once.
        self.assertAlmostEqual(
            self.components.all_in_price(0.1877), 0.278639122, places=9
        )

    def test_a_different_vat_rate_is_honoured(self) -> None:
        # The rate is statutory and has changed before: nothing may bake in 1.06.
        at_21 = tariffs.TariffComponents(
            components=self.components.components, vat_rate=0.21
        )
        self.assertAlmostEqual(at_21.total_incl_vat, 0.089810677, places=9)

    def test_zero_vat_leaves_the_sum_untouched(self) -> None:
        free = tariffs.TariffComponents(
            components=self.components.components, vat_rate=0.0
        )
        self.assertEqual(free.total_incl_vat, free.total_excl_vat)
        self.assertEqual(free.all_in_price(0.1877), free.total_excl_vat + 0.1877)

    def test_newest_valid_from_is_the_latest_component(self) -> None:
        mixed = tariffs.TariffComponents(
            components=(component("network", 0.063, 2026), component("gsc", 0.011, 2024))
        )
        self.assertEqual(mixed.newest_valid_from, date(2026, 1, 1))

    def test_attributes_name_every_component_and_its_provenance(self) -> None:
        attributes = self.components.as_attributes()
        self.assertAlmostEqual(attributes["network"], 0.0631937, places=9)
        self.assertEqual(attributes["network_source"], "test network")
        self.assertEqual(attributes["network_valid_from"], "2026-01-01")
        self.assertEqual(attributes["vat_rate"], 0.06)
        self.assertEqual(attributes["vat_basis"], "incl")

    def test_default_vat_rate_is_six_percent(self) -> None:
        self.assertEqual(tariffs.DEFAULT_VAT_RATE, 0.06)
        self.assertEqual(
            tariffs.TariffComponents(components=()).vat_rate, 0.06
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — no module `tariffs`.

- [ ] **Step 3: Write the model**

```python
"""Everything about what a kWh of electricity costs besides the energy itself.

The integration scrapes one number: the energy component, excl. VAT. The rest of
the bill's per-kWh price -- the green-certificate and cogeneration levies, the
distribution network tariff, the excise and the energy levy -- is published by
the regulator and by law, not by the supplier's website, and is assembled here.

Two rules hold throughout this module, and the design depends on both:

* **Every value is excl. VAT.** Sources that publish incl. VAT are divided once,
  where they are read, and record the basis they were published on.
* **VAT is applied in one place**, ``TariffComponents``. A mixed VAT basis is the
  characteristic failure of hand-assembled tariff arithmetic: it yields a figure
  that looks entirely plausible and is quietly 3.5% low.

This module does no I/O and knows nothing about Home Assistant, so it can be
tested against saved copies of the real spreadsheets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# Belgian VAT on domestic electricity. Statutory, and it has changed before --
# it was 6% until 2015, 21% until 2022, 6% since -- so it is an option, not a
# constant to multiply by in passing.
DEFAULT_VAT_RATE = 0.06

# Keys an all-in price needs before it may be published. Fewer than all of them
# does not make the price smaller, it makes it wrong.
REQUIRED_KEYS = frozenset({"network", "gsc", "wkk", "excise", "energy_levy"})


class TariffError(Exception):
    """Raised when published figures cannot be turned into components."""


@dataclass(frozen=True)
class Component:
    """One priced line of the per-kWh build-up, always stored excl. VAT."""

    key: str
    value: float
    source: str
    valid_from: date
    valid_until: date | None = None


@dataclass(frozen=True)
class TariffComponents:
    """The components that sit on top of the energy price, and their VAT rate."""

    components: tuple[Component, ...]
    vat_rate: float = DEFAULT_VAT_RATE

    @property
    def total_excl_vat(self) -> float:
        """Sum of every component, excl. VAT."""
        return sum(component.value for component in self.components)

    @property
    def total_incl_vat(self) -> float:
        """Sum of every component, incl. VAT. The only conversion in the code."""
        return self.total_excl_vat * (1 + self.vat_rate)

    def all_in_price(self, energy_excl_vat: float) -> float:
        """Return what a kWh costs: energy plus components, taxed once."""
        return (energy_excl_vat + self.total_excl_vat) * (1 + self.vat_rate)

    @property
    def newest_valid_from(self) -> date:
        """The most recent validity date among the components."""
        return max(component.valid_from for component in self.components)

    def keys(self) -> frozenset[str]:
        """The component keys present."""
        return frozenset(component.key for component in self.components)

    def as_attributes(self) -> dict[str, object]:
        """Flatten to sensor attributes: every component with its provenance."""
        attributes: dict[str, object] = {
            "vat_rate": self.vat_rate,
            "vat_basis": "incl",
            "total_components": round(self.total_incl_vat, 6),
        }
        for component in self.components:
            attributes[component.key] = round(component.value, 9)
            attributes[f"{component.key}_source"] = component.source
            attributes[f"{component.key}_valid_from"] = component.valid_from.isoformat()
        return attributes
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 8 new tests, PASS (14 total).

- [ ] **Step 5: Commit**

```bash
git add custom_components/energiebe/tariffs.py tests/test_tariffs_model.py
git commit -m "feat: add the tariff component model with a single VAT conversion"
```

---

### Task 3: Parse the distribution network tariffs

**Files:**
- Modify: `custom_components/energiebe/tariffs.py`
- Create: `tests/test_network_tariffs.py`

**Interfaces:**
- Consumes: `read_xlsx` output (`dict[str, list[list[str]]]`), `Component`, `TariffError`.
- Produces: `parse_network_tariffs(sheets, *, operator, meter_kind="digital", scheme="single") -> Component` (key `"network"`, €/kWh excl. VAT); `network_operators(sheets) -> tuple[str, ...]`; `METER_KINDS`, `TARIFF_SCHEMES`.

The sheet's verified shape (`ELEK Overzicht laagspanning`), matched by text, never by index:

```
a row whose columns 3..10 are the eight operator names   <- column lookup
a row whose column 0 is "Exclusief btw"   and column 1 "Digitale meter"   <- block start
   rows with a label in column 1, a unit in column 2, values in columns 3..10
a row whose column 0 is "Inclusief 6% btw" and column 1 "Digitale meter"   <- next block
a row whose column 0 is "Exclusief btw"   and column 1 "Analoge meter"
a row whose column 0 is "Inclusief 6% btw" and column 1 "Analoge meter"
a row containing "Deze tarieflijst geldt van 01/01/2026 t.e.m. 31/12/2026."
```

Resolves spec open question 6: the classic-meter block is labelled **`Analoge meter`**, not `Klassieke meter`, and it repeats the digital block's shape for the rows this task reads.

- [ ] **Step 1: Write the failing test**

```python
"""Parsing the VREG distribution network tariffs."""

import unittest
from datetime import date

from loader import fixture, load

tariffs = load("tariffs")
xlsx = load("xlsx")


class TestNetworkTariffs(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sheets = xlsx.read_xlsx(fixture("nettarieven-2026.xlsx"))

    def parse(self, **kwargs: object) -> object:
        return tariffs.parse_network_tariffs(self.sheets, **kwargs)

    def test_fluvius_west_digital_single(self) -> None:
        component = self.parse(operator="Fluvius West")
        # 63.1937 EUR/MWh excl. VAT -> EUR/kWh.
        self.assertAlmostEqual(component.value, 0.0631937, places=9)
        self.assertEqual(component.key, "network")
        self.assertIn("Fluvius West", component.source)

    def test_validity_comes_from_the_sheet_not_the_clock(self) -> None:
        component = self.parse(operator="Fluvius West")
        self.assertEqual(component.valid_from, date(2026, 1, 1))
        self.assertEqual(component.valid_until, date(2026, 12, 31))

    def test_vat_conversion_matches_vregs_own_inclusive_block(self) -> None:
        # The file ships both bases. We read the exclusive one, so the inclusive
        # one is an independent oracle for our single conversion.
        component = self.parse(operator="Fluvius West")
        priced = tariffs.TariffComponents(components=(component,), vat_rate=0.06)
        self.assertAlmostEqual(priced.total_incl_vat * 1000, 66.9853, delta=1e-4)

    def test_every_operator_resolves(self) -> None:
        operators = tariffs.network_operators(self.sheets)
        self.assertEqual(len(operators), 8)
        self.assertIn("Fluvius West", operators)
        for operator in operators:
            self.assertGreater(self.parse(operator=operator).value, 0.0)

    def test_operator_names_are_whitespace_normalised(self) -> None:
        # The cells hold 'Fluvius\nAntwerpen' and 'Fluvius \nHalle-Vilvoorde'.
        operators = tariffs.network_operators(self.sheets)
        self.assertIn("Fluvius Antwerpen", operators)
        self.assertIn("Fluvius Halle-Vilvoorde", operators)
        self.assertAlmostEqual(
            self.parse(operator="Fluvius Antwerpen").value, 0.0505027, places=9
        )

    def test_night_only_reads_the_exclusief_nacht_row(self) -> None:
        component = self.parse(operator="Fluvius West", scheme="night_only")
        self.assertAlmostEqual(component.value, 0.056536, places=9)

    def test_dual_schemes_use_the_same_volume_tariff(self) -> None:
        # The distribution tariff for a digital meter does not split day/night.
        day = self.parse(operator="Fluvius West", scheme="dual_day")
        night = self.parse(operator="Fluvius West", scheme="dual_night")
        self.assertEqual(day.value, night.value)
        self.assertAlmostEqual(day.value, 0.0631937, places=9)

    def test_analogue_meter_reads_its_own_block(self) -> None:
        component = self.parse(operator="Fluvius West", meter_kind="classic")
        self.assertAlmostEqual(component.value, 0.0971801, places=9)
        self.assertIn("Analoge meter", component.source)

    def test_unknown_operator_is_refused_loudly(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            self.parse(operator="Sibelga")

    def test_implausible_value_is_refused(self) -> None:
        # A reshaped sheet could put Maximumtarief (327.6 EUR/MWh) where the
        # real tariff was. Five times the plausible price must not be published.
        broken = {
            name: [list(row) for row in rows] for name, rows in self.sheets.items()
        }
        rows = broken["ELEK Overzicht laagspanning"]
        row = next(r for r in rows if len(r) > 9 and r[1] == "Totaal kWh-tarief")
        row[9] = "327.6168"
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_network_tariffs(broken, operator="Fluvius West")

    def test_unparseable_value_is_refused(self) -> None:
        broken = {
            name: [list(row) for row in rows] for name, rows in self.sheets.items()
        }
        rows = broken["ELEK Overzicht laagspanning"]
        row = next(r for r in rows if len(r) > 9 and r[1] == "Totaal kWh-tarief")
        row[9] = "n.v.t."
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_network_tariffs(broken, operator="Fluvius West")

    def test_missing_sheet_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_network_tariffs({}, operator="Fluvius West")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `module 'tariffs' has no attribute 'parse_network_tariffs'`.

- [ ] **Step 3: Implement the parser**

Append to `tariffs.py`:

```python
import re

_NETWORK_SHEET = "ELEK Overzicht laagspanning"

# The blocks the sheet repeats, keyed by the meter the user has. VREG labels the
# non-digital one "Analoge meter"; "klassieke meter" is the invoice's wording.
METER_KINDS: dict[str, str] = {"digital": "Digitale meter", "classic": "Analoge meter"}

# Which row of the block a tariff scheme pays. A digital meter's distribution
# tariff does not split day from night, so only the exclusive-night register
# has its own, lower, row.
TARIFF_SCHEMES: dict[str, str] = {
    "single": "Totaal kWh-tarief",
    "dual_day": "Totaal kWh-tarief",
    "dual_night": "Totaal kWh-tarief",
    "night_only": "Totaal kWh-tarief - exclusief nacht",
}

_EXCL_VAT = "Exclusief btw"
_VALIDITY = re.compile(r"geldt van (\d{2})/(\d{2})/(\d{4}) t\.e\.m\. (\d{2})/(\d{2})/(\d{4})")

# Flemish distribution tariffs run from about 45 to 100 EUR/MWh across operators
# and meter kinds. Maximumtarief, which sits in the same block, is 327. Refuse
# anything outside a band that cannot be confused with another row.
_MIN_NETWORK_EUR_MWH = 10.0
_MAX_NETWORK_EUR_MWH = 200.0


def _text(row: list[str], index: int) -> str:
    """Return a cell with its whitespace collapsed; cells hold newlines."""
    if index >= len(row):
        return ""
    return " ".join(row[index].split())


def _network_sheet(sheets: dict[str, list[list[str]]]) -> list[list[str]]:
    if _NETWORK_SHEET not in sheets:
        raise TariffError(
            f"No {_NETWORK_SHEET!r} sheet; the workbook has {sorted(sheets)}"
        )
    return sheets[_NETWORK_SHEET]


def _operator_row(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Find the row naming the operators, and which column each one is in."""
    for index, row in enumerate(rows):
        columns = {
            column: _text(row, column)
            for column in range(len(row))
            if _text(row, column).startswith("Fluvius")
        }
        if len(columns) >= 2:
            return index, {name: column for column, name in columns.items()}
    raise TariffError(f"No operator header row in {_NETWORK_SHEET!r}")


def network_operators(sheets: dict[str, list[list[str]]]) -> tuple[str, ...]:
    """Return the distribution network operators the file carries, in order."""
    _, columns = _operator_row(_network_sheet(sheets))
    return tuple(columns)


def _validity(rows: list[list[str]]) -> tuple[date, date]:
    """Read the period the tariff list is approved for out of its own notes."""
    for row in rows:
        for cell in row:
            if match := _VALIDITY.search(cell):
                day, month, year, until_day, until_month, until_year = match.groups()
                return (
                    date(int(year), int(month), int(day)),
                    date(int(until_year), int(until_month), int(until_day)),
                )
    raise TariffError(f"No validity period stated in {_NETWORK_SHEET!r}")


def parse_network_tariffs(
    sheets: dict[str, list[list[str]]],
    *,
    operator: str,
    meter_kind: str = "digital",
    scheme: str = "single",
) -> Component:
    """Return the distribution network component, in EUR/kWh excl. VAT."""
    if meter_kind not in METER_KINDS:
        raise TariffError(f"Unknown meter kind {meter_kind!r}")
    if scheme not in TARIFF_SCHEMES:
        raise TariffError(f"Unknown tariff scheme {scheme!r}")

    rows = _network_sheet(sheets)
    header, columns = _operator_row(rows)
    wanted = " ".join(operator.split())
    if wanted not in columns:
        raise TariffError(f"Unknown operator {operator!r}; the file has {sorted(columns)}")

    block_label = METER_KINDS[meter_kind]
    row_label = TARIFF_SCHEMES[scheme]
    inside = False
    for row in rows[header + 1 :]:
        marker = _text(row, 0)
        if marker:
            # A block header: "Exclusief btw" / "Inclusief 6% btw" plus the meter.
            inside = marker == _EXCL_VAT and _text(row, 1) == block_label
            continue
        if not inside or _text(row, 1) != row_label:
            continue
        raw = _text(row, columns[wanted])
        try:
            per_mwh = float(raw)
        except ValueError as err:
            raise TariffError(
                f"{row_label!r} for {wanted} is not a number: {raw!r}"
            ) from err
        if not _MIN_NETWORK_EUR_MWH < per_mwh < _MAX_NETWORK_EUR_MWH:
            raise TariffError(
                f"Implausible {row_label!r} for {wanted}: {per_mwh} EUR/MWh"
            )
        valid_from, valid_until = _validity(rows)
        return Component(
            key="network",
            value=per_mwh / 1000,
            source=f"VREG distributienettarieven {valid_from.year}, {wanted}, {block_label}",
            valid_from=valid_from,
            valid_until=valid_until,
        )

    raise TariffError(f"No {row_label!r} row in the {block_label!r} {_EXCL_VAT} block")
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 12 new tests, PASS (26 total).

- [ ] **Step 5: Commit**

```bash
git add custom_components/energiebe/tariffs.py tests/test_network_tariffs.py
git commit -m "feat: read the distribution network tariff from the VREG file"
```

---

### Task 4: Parse the V-test levies, with a trimmed fixture

**Files:**
- Modify: `custom_components/energiebe/tariffs.py`
- Create: `tools/trim_vtest.py`
- Create: `tests/fixtures/vtest-202610.xlsx`
- Create: `tests/test_vtest.py`

**Interfaces:**
- Consumes: `read_xlsx` output, `Component`, `TariffError`, `_text`.
- Produces: `parse_vtest(sheets, *, supplier, product, month, segment="Woning") -> dict[str, Component]` (keys `"gsc"`, `"wkk"`); `vtest_suppliers(sheets)`; `vtest_products(sheets, *, supplier, segment="Woning")`; `vtest_months(sheets)`. No `scheme` argument: the V-test rows that differ per scheme are the energy formula (`Enkelvoudige meter dagtarief`, `Tweevoudige meter …`, `Uitsluitend nachtmeter`), which this integration scrapes off the website instead of computing. The two levies it reads are the same on every scheme — verified in the October 2026 file. `tariff_scheme` therefore only selects a row in the network tariff sheet (Task 3).

The sheet is `Var-dyn (excl. btw) (2026)`, one row per priced line, with the verified column meanings: 0 Year, 1 Month (`jan`…`dec`, Dutch), 2 Segment (`Woning`/`Onderneming`), 4 Contracttype (`Afname`/`Injectie`/`Teruglevering`), 5 Handelsnaam, 6 Productnaam, 8 Prijsonderdeel, 30 Prijs. Flat components carry column 30; indexed ones carry coefficients in 25–29 and leave 30 empty — the two levies this task reads are flat.

- [ ] **Step 1: Write the trimming tool**

The full file is 4 MB, 18 146 rows, and would be a 4 MB fixture refreshed monthly. Trim it to two suppliers while keeping every real part — `sharedStrings.xml`, `styles.xml`, the relationships — byte for byte, so shared-string indices and the column layout stay exactly as the regulator published them. The three sheets this integration never reads are replaced with an empty stub so the workbook stays internally consistent.

```python
"""Trim a V-test workbook to the suppliers a fixture needs.

The published file is 4 MB of every supplier's every month. A fixture only needs
a couple of suppliers, but it must keep the real shared strings, styles and
relationships: shared-string indices are positional, so rebuilding them would
make the fixture prove something the real file does not.

Usage:
    python3 tools/trim_vtest.py <source.xlsx> <dest.xlsx> "Energie.be" "Aspiravi Energy"
"""

from __future__ import annotations

import sys
import zipfile
from xml.etree import ElementTree as ET

_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_KEEP = "xl/worksheets/sheet3.xml"  # Var-dyn (excl. btw) (<year>)
_STUB = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    b"<sheetData/></worksheet>"
)
_DROP = {
    "xl/worksheets/sheet2.xml",
    "xl/worksheets/sheet4.xml",
    "xl/worksheets/sheet5.xml",
}
_SUPPLIER_COLUMN = 5


def _column(ref: str) -> int:
    number = 0
    for char in ref:
        if not char.isalpha():
            break
        number = number * 26 + (ord(char.upper()) - 64)
    return number - 1


def main() -> None:
    source, dest, *suppliers = sys.argv[1:]
    wanted = {" ".join(name.split()) for name in suppliers}
    archive = zipfile.ZipFile(source)
    shared = [
        "".join(text.text or "" for text in item.iter(f"{_MAIN}t"))
        for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).iter(f"{_MAIN}si")
    ]

    kept: list[str] = []
    for position, (_, row) in enumerate(ET.iterparse(archive.open(_KEEP)), start=0):
        if not row.tag.endswith("}row"):
            continue
        keep = position == 0  # the header row
        for cell in row.iter(f"{_MAIN}c"):
            if _column(cell.get("r") or "") != _SUPPLIER_COLUMN:
                continue
            value = cell.find(f"{_MAIN}v")
            if cell.get("t") == "s" and value is not None and value.text is not None:
                keep = keep or " ".join(shared[int(value.text)].split()) in wanted
        if keep:
            kept.append(
                ET.tostring(row, encoding="unicode").replace(_MAIN, "").replace("ns0:", "")
            )
        row.clear()

    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(kept) + "</sheetData></worksheet>"
    ).encode()

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
        for item in archive.infolist():
            if item.filename == _KEEP:
                out.writestr(item.filename, sheet)
            elif item.filename in _DROP:
                out.writestr(item.filename, _STUB)
            else:
                out.writestr(item, archive.read(item.filename))

    print(f"kept {len(kept)} rows")


if __name__ == "__main__":
    main()
```

Note: `ET.iterparse` yields the header row first, so `position == 0` is it. If a future file changes which sheet number holds `Var-dyn`, read `xl/workbook.xml` to find it rather than editing `_KEEP` blindly.

- [ ] **Step 2: Build the fixture**

```bash
curl -sSL -o /tmp/vtest-full.xlsx \
  'https://assets.vlaamsenutsregulator.be/2026-10/202610-v-test-data-exclbtw%20v2_0.xlsx'
python3 tools/trim_vtest.py /tmp/vtest-full.xlsx tests/fixtures/vtest-202610.xlsx \
  "Energie.be" "Aspiravi Energy"
ls -l tests/fixtures/vtest-202610.xlsx
```

Expected: `kept 491 rows` (381 Energie.be + 110 Aspiravi + header), about 60 kB. The exact count may differ if VREG republishes the month; the assertions below are on values, not counts.

- [ ] **Step 3: Write the failing test**

```python
"""Parsing the VREG V-test levies."""

import unittest
from datetime import date

from loader import fixture, load

tariffs = load("tariffs")
xlsx = load("xlsx")

OCTOBER = date(2026, 10, 1)


class TestVtest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sheets = xlsx.read_xlsx(fixture("vtest-202610.xlsx"))

    def parse(self, **kwargs: object) -> dict:
        arguments = {
            "supplier": "Energie.be",
            "product": "Elektriciteit online",
            "month": OCTOBER,
        }
        arguments.update(kwargs)
        return tariffs.parse_vtest(self.sheets, **arguments)

    def test_green_certificate_and_cogeneration_levies(self) -> None:
        components = self.parse()
        # 1.103 and 0.364 c€/kWh excl. VAT -> EUR/kWh.
        self.assertAlmostEqual(components["gsc"].value, 0.01103, places=9)
        self.assertAlmostEqual(components["wkk"].value, 0.00364, places=9)

    def test_source_names_the_file_and_the_month(self) -> None:
        component = self.parse()["gsc"]
        self.assertIn("V-test", component.source)
        self.assertIn("2026-10", component.source)
        self.assertEqual(component.valid_from, OCTOBER)

    def test_both_levies_are_excl_vat_as_published(self) -> None:
        # VREG states "Alle prijzen zijn exclusief btw"; the card's 1.169 and
        # 0.386 c€/kWh are these values with VAT, which is the check that the
        # basis has not been mixed up.
        components = self.parse()
        self.assertAlmostEqual(components["gsc"].value * 1.06, 0.0116918, places=9)
        self.assertAlmostEqual(components["wkk"].value * 1.06, 0.0038584, places=9)

    def test_a_month_not_in_the_file_falls_back_to_the_newest(self) -> None:
        # In early November the October file is still the newest published.
        components = self.parse(month=date(2026, 11, 1))
        self.assertAlmostEqual(components["gsc"].value, 0.01103, places=9)
        self.assertIn("2026-10", components["gsc"].source)
        self.assertEqual(components["gsc"].valid_from, OCTOBER)

    def test_an_earlier_month_reads_that_month(self) -> None:
        components = self.parse(month=date(2026, 1, 1))
        self.assertIn("2026-01", components["gsc"].source)
        self.assertEqual(components["gsc"].valid_from, date(2026, 1, 1))

    def test_supplier_names_are_whitespace_normalised(self) -> None:
        # The cell holds 'Aspiravi Energy ' with a trailing space.
        suppliers = tariffs.vtest_suppliers(self.sheets)
        self.assertIn("Energie.be", suppliers)
        self.assertIn("Aspiravi Energy", suppliers)

    def test_products_are_listed_per_supplier(self) -> None:
        products = tariffs.vtest_products(self.sheets, supplier="Energie.be")
        self.assertIn("Elektriciteit online", products)
        self.assertIn("Elektriciteit dynamisch online", products)
        # Gas and business products must not be offered as an electricity choice.
        self.assertNotIn("Gas online", products)
        self.assertNotIn("Elektriciteit professioneel online", products)

    def test_business_segment_reads_its_own_rows(self) -> None:
        components = self.parse(
            segment="Onderneming", product="Elektriciteit professioneel online"
        )
        self.assertAlmostEqual(components["gsc"].value, 0.01103, places=9)

    def test_months_are_listed_newest_first(self) -> None:
        months = tariffs.vtest_months(self.sheets)
        self.assertEqual(months[0], OCTOBER)
        self.assertIn(date(2026, 1, 1), months)

    def test_unknown_supplier_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            self.parse(supplier="Nuon")

    def test_unknown_product_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            self.parse(product="Elektriciteit offline")

    def test_ambiguous_match_is_refused(self) -> None:
        # Two rows for one component means the filter no longer identifies a
        # single product; publishing either would be a guess.
        doubled = {
            name: [list(row) for row in rows] for name, rows in self.sheets.items()
        }
        rows = doubled["Var-dyn (excl. btw) (2026)"]
        row = next(
            r
            for r in rows[1:]
            if len(r) > 30
            and r[1] == "okt"
            and r[5] == "Energie.be"
            and r[6] == "Elektriciteit online"
            and r[8].startswith("Kosten groene stroom")
        )
        rows.append(list(row))
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_vtest(
                doubled,
                supplier="Energie.be",
                product="Elektriciteit online",
                month=OCTOBER,
            )

    def test_missing_sheet_is_refused(self) -> None:
        with self.assertRaises(tariffs.TariffError):
            tariffs.parse_vtest(
                {}, supplier="Energie.be", product="Elektriciteit online", month=OCTOBER
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `module 'tariffs' has no attribute 'parse_vtest'`.

- [ ] **Step 5: Implement the parser**

Append to `tariffs.py`:

```python
# VREG names the V-test sheet after the year it covers.
_VTEST_SHEET_PREFIX = "Var-dyn (excl. btw)"

# The sheet writes months as Dutch three-letter abbreviations.
_MONTHS: dict[str, int] = {
    "jan": 1, "feb": 2, "mrt": 3, "apr": 4, "mei": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}

# Columns, verified against the October 2026 file.
_VT_YEAR, _VT_MONTH, _VT_SEGMENT = 0, 1, 2
_VT_CONTRACT, _VT_SUPPLIER, _VT_PRODUCT = 4, 5, 6
_VT_LINE, _VT_PRICE = 8, 30

# The two per-kWh levies this integration needs, by the line they are published
# under. Everything else in the sheet is either the energy formula itself (which
# we scrape instead) or a standing charge (out of scope, see the spec).
_VTEST_LEVIES: dict[str, str] = {
    "gsc": "Kosten groene stroom (c€/kWh)",
    "wkk": "Kosten WKK (c€/kWh)",
}

# Both levies are a few tenths of a c€/kWh. A euro per kWh means we read the
# wrong column.
_MAX_LEVY_CENTS = 100.0


def _vtest_sheet(sheets: dict[str, list[list[str]]]) -> list[list[str]]:
    for name, rows in sheets.items():
        if name.startswith(_VTEST_SHEET_PREFIX):
            return rows
    raise TariffError(
        f"No {_VTEST_SHEET_PREFIX!r} sheet; the workbook has {sorted(sheets)}"
    )


def _vtest_month(row: list[str]) -> date | None:
    month = _MONTHS.get(_text(row, _VT_MONTH).lower())
    year = _text(row, _VT_YEAR)
    if month is None or not year.isdigit():
        return None
    return date(int(year), month, 1)


def _is_electricity_consumption(row: list[str]) -> bool:
    return _text(row, _VT_CONTRACT) == "Afname" and _text(
        row, _VT_PRODUCT
    ).lower().startswith("elektriciteit")


def vtest_suppliers(sheets: dict[str, list[list[str]]]) -> tuple[str, ...]:
    """Return every supplier the file carries, sorted, whitespace normalised."""
    rows = _vtest_sheet(sheets)
    names = {
        _text(row, _VT_SUPPLIER)
        for row in rows[1:]
        if _text(row, _VT_SUPPLIER) and _vtest_month(row) is not None
    }
    return tuple(sorted(names))


def vtest_products(
    sheets: dict[str, list[list[str]]], *, supplier: str, segment: str = "Woning"
) -> tuple[str, ...]:
    """Return a supplier's electricity consumption products for a segment."""
    wanted = " ".join(supplier.split())
    products = {
        _text(row, _VT_PRODUCT)
        for row in _vtest_sheet(sheets)[1:]
        if _text(row, _VT_SUPPLIER) == wanted
        and _text(row, _VT_SEGMENT) == segment
        and _is_electricity_consumption(row)
    }
    return tuple(sorted(products))


def vtest_months(sheets: dict[str, list[list[str]]]) -> tuple[date, ...]:
    """Return the months the file carries, newest first."""
    months = {
        month
        for row in _vtest_sheet(sheets)[1:]
        if (month := _vtest_month(row)) is not None
    }
    return tuple(sorted(months, reverse=True))


def parse_vtest(
    sheets: dict[str, list[list[str]]],
    *,
    supplier: str,
    product: str,
    month: date,
    segment: str = "Woning",
) -> dict[str, Component]:
    """Return the per-kWh levies a supplier's product carries, excl. VAT.

    The newest file is published during the month it covers, so a request for a
    month the file does not carry yet reads the newest month present and says so
    in the component's source rather than failing.
    """
    rows = _vtest_sheet(sheets)
    wanted_supplier = " ".join(supplier.split())
    wanted_product = " ".join(product.split())

    available = vtest_months(sheets)
    if not available:
        raise TariffError("The V-test sheet carries no months")
    asked = date(month.year, month.month, 1)
    if asked in available:
        effective = asked
    elif earlier := [candidate for candidate in available if candidate <= asked]:
        # The file for the current month appears during that month, so until it
        # does the newest month present is the right answer, not an error.
        effective = max(earlier)
    else:
        effective = min(available)

    components: dict[str, Component] = {}
    for key, line in _VTEST_LEVIES.items():
        matches = [
            row
            for row in rows[1:]
            if _vtest_month(row) == effective
            and _text(row, _VT_SEGMENT) == segment
            and _text(row, _VT_CONTRACT) == "Afname"
            and _text(row, _VT_SUPPLIER) == wanted_supplier
            and _text(row, _VT_PRODUCT) == wanted_product
            and _text(row, _VT_LINE) == line
        ]
        if not matches:
            raise TariffError(
                f"No {line!r} row for {wanted_supplier} / {wanted_product} / "
                f"{segment} / {effective:%Y-%m}"
            )
        if len(matches) > 1:
            raise TariffError(
                f"{len(matches)} rows match {line!r} for {wanted_supplier} / "
                f"{wanted_product} / {effective:%Y-%m}; cannot tell them apart"
            )
        raw = _text(matches[0], _VT_PRICE)
        try:
            cents = float(raw)
        except ValueError as err:
            raise TariffError(f"{line!r} is not a number: {raw!r}") from err
        if not 0 <= cents < _MAX_LEVY_CENTS:
            raise TariffError(f"Implausible {line!r}: {cents} c€/kWh")
        components[key] = Component(
            key=key,
            value=cents / 100,
            source=(
                f"VREG V-test {effective:%Y-%m} (excl. btw), "
                f"{wanted_supplier} / {wanted_product}"
            ),
            valid_from=effective,
            valid_until=None,
        )
    return components
```

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 13 new tests, PASS (39 total).

- [ ] **Step 7: Commit**

```bash
git add custom_components/energiebe/tariffs.py tools/trim_vtest.py \
  tests/fixtures/vtest-202610.xlsx tests/test_vtest.py
git commit -m "feat: read the green-certificate and cogeneration levies from the V-test"
```

---

### Task 5: The statutory levy table

**Files:**
- Modify: `custom_components/energiebe/tariffs.py`
- Create: `tests/test_statutory.py`

**Interfaces:**
- Consumes: `Component`.
- Produces: `STATUTORY_TABLE` (the quotable figures, as published), `statutory_components(vat_rate=DEFAULT_VAT_RATE) -> tuple[Component, ...]` (keys `"excise"`, `"energy_levy"`, excl. VAT).

Neither VREG file carries these; the V-test says so explicitly. They change by legislation, not on a schedule, so they ship in the repository with the figure exactly as published, the document it came from, and its VAT basis — and are normalised to excl. VAT at the point of use, so the repository keeps the quotable number and the code keeps one basis.

**Spec open question 7 is implemented, not resolved.** Both readings of the card are defensible, the difference is 0.3 c€/kWh, and the table records the card's literal reading (`vat_basis="incl"`) with the reason in `source`, so the choice is visible in the sensor's attributes. Switching readings is changing `"incl"` to `"excl"` on two rows; the test below pins both outcomes so the switch cannot be made silently.

- [ ] **Step 1: Write the failing test**

```python
"""The bundled statutory levies."""

import unittest
from datetime import date

from loader import load

tariffs = load("tariffs")


class TestStatutory(unittest.TestCase):
    def components(self, **kwargs: object) -> dict:
        return {c.key: c for c in tariffs.statutory_components(**kwargs)}

    def test_both_levies_are_present(self) -> None:
        self.assertEqual(set(self.components()), {"excise", "energy_levy"})

    def test_card_figures_are_stored_as_published(self) -> None:
        published = {row["key"]: row for row in tariffs.STATUTORY_TABLE}
        self.assertEqual(published["excise"]["cents_per_kwh"], 5.0329)
        self.assertEqual(published["energy_levy"]["cents_per_kwh"], 0.2042)
        for row in published.values():
            self.assertIn(row["vat_basis"], {"incl", "excl"})
            self.assertTrue(row["source"])
            self.assertIsInstance(row["valid_from"], date)

    def test_an_inclusive_figure_is_divided_once(self) -> None:
        # Stored incl. VAT at 5.0329 c€/kWh; every value leaving this module is
        # excl. VAT, so 0.050329 / 1.06.
        excise = self.components()["excise"]
        self.assertAlmostEqual(excise.value, 0.047480189, places=9)
        self.assertAlmostEqual(excise.value * 1.06, 0.050329, places=9)

    def test_the_vat_basis_is_recorded_in_the_source(self) -> None:
        excise = self.components()["excise"]
        self.assertIn("incl", excise.source)
        self.assertIn("tariefkaart", excise.source.lower())

    def test_a_different_vat_rate_changes_the_normalisation(self) -> None:
        at_21 = self.components(vat_rate=0.21)["excise"]
        self.assertAlmostEqual(at_21.value, 0.050329 / 1.21, places=9)

    def test_switching_the_statutory_reading_is_a_one_line_change(self) -> None:
        # Open question 7: if the card's 5.0329 turns out to be the excl.-VAT
        # statutory rate, the table's vat_basis becomes "excl" and the value is
        # taken as-is. This pins what that would produce, so the two readings
        # cannot be confused later.
        as_excl = tariffs._normalise(
            cents_per_kwh=5.0329, vat_basis="excl", vat_rate=0.06
        )
        self.assertAlmostEqual(as_excl, 0.050329, places=9)
        self.assertAlmostEqual(as_excl * 1.06, 0.05334874, places=9)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `module 'tariffs' has no attribute 'statutory_components'`.

- [ ] **Step 3: Implement the table**

Append to `tariffs.py`:

```python
# Levies set by law rather than by a regulator's spreadsheet. Neither VREG file
# carries them -- the V-test states "De nettarieven en heffingen zijn niet
# opgenomen in dit bestand" -- so they live here, each recording the figure
# exactly as published, the document it came from, and the VAT basis that
# document used.
#
# vat_basis is the open question of the design. The Energie.be tariff card says
# "Alle prijzen zijn inclusief btw tenzij anders vermeld" and marks only the
# Energiefonds contribution otherwise, which makes these two incl. VAT. But a
# statutory excise rate is normally set excl. VAT with VAT levied on top, and
# secondary sources quote 5.0329 c€/kWh as the excl.-VAT rate. The card's own
# reading is used here because it is the document in hand; it is recorded in the
# source so the choice shows up in the sensor's attributes instead of being
# buried. Settling it against an invoice line moves the all-in price by about
# 0.3 c€/kWh: 0.3339 becomes 0.3370 EUR/kWh.
STATUTORY_TABLE: tuple[dict[str, object], ...] = (
    {
        "key": "excise",
        "cents_per_kwh": 5.0329,
        "vat_basis": "incl",
        "valid_from": date(2026, 10, 1),
        "source": "Energie.be tariefkaart oktober 2026, Taksen en heffingen "
        "(Bijzondere accijns op energie, incl. btw volgens de kaart)",
    },
    {
        "key": "energy_levy",
        "cents_per_kwh": 0.2042,
        "vat_basis": "incl",
        "valid_from": date(2026, 10, 1),
        "source": "Energie.be tariefkaart oktober 2026, Taksen en heffingen "
        "(Bijdrage op de energie, incl. btw volgens de kaart)",
    },
)


def _normalise(*, cents_per_kwh: float, vat_basis: str, vat_rate: float) -> float:
    """Return a published figure as EUR/kWh excl. VAT."""
    value = cents_per_kwh / 100
    if vat_basis == "excl":
        return value
    if vat_basis == "incl":
        return value / (1 + vat_rate)
    raise TariffError(f"Unknown VAT basis {vat_basis!r}")


def statutory_components(
    vat_rate: float = DEFAULT_VAT_RATE,
) -> tuple[Component, ...]:
    """Return the statutory levies as components, excl. VAT."""
    return tuple(
        Component(
            key=str(row["key"]),
            value=_normalise(
                cents_per_kwh=float(row["cents_per_kwh"]),
                vat_basis=str(row["vat_basis"]),
                vat_rate=vat_rate,
            ),
            source=str(row["source"]),
            valid_from=row["valid_from"],  # type: ignore[arg-type]
            valid_until=None,
        )
        for row in STATUTORY_TABLE
    )
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 6 new tests, PASS (45 total).

- [ ] **Step 5: Commit**

```bash
git add custom_components/energiebe/tariffs.py tests/test_statutory.py
git commit -m "feat: bundle the statutory levies with their published basis"
```

---

### Task 6: Assemble the components, and refuse a partial price

**Files:**
- Modify: `custom_components/energiebe/tariffs.py`
- Create: `tests/test_build.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build(*, network, vtest, vat_rate=DEFAULT_VAT_RATE) -> TariffComponents`; `stale_reasons(components, today) -> tuple[str, ...]`; `REQUIRED_KEYS`.

- [ ] **Step 1: Write the failing test**

```python
"""Assembling the components, end to end, from the real fixtures."""

import unittest
from datetime import date

from loader import fixture, load

tariffs = load("tariffs")
xlsx = load("xlsx")

OCTOBER = date(2026, 10, 1)
SCRAPED_ENERGY = 0.1877  # what the website published on 2026-10-17, excl. VAT


class TestBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.network_sheets = xlsx.read_xlsx(fixture("nettarieven-2026.xlsx"))
        cls.vtest_sheets = xlsx.read_xlsx(fixture("vtest-202610.xlsx"))

    def components(self, **kwargs: object) -> object:
        return tariffs.build(
            network=tariffs.parse_network_tariffs(
                self.network_sheets, operator="Fluvius West"
            ),
            vtest=tariffs.parse_vtest(
                self.vtest_sheets,
                supplier="Energie.be",
                product="Elektriciteit online",
                month=OCTOBER,
            ),
            **kwargs,
        )

    def test_every_required_component_is_present(self) -> None:
        self.assertEqual(self.components().keys(), tariffs.REQUIRED_KEYS)

    def test_components_total(self) -> None:
        components = self.components()
        self.assertAlmostEqual(components.total_excl_vat, 0.127270304, places=9)
        self.assertAlmostEqual(components.total_incl_vat, 0.134906522, places=9)

    def test_all_in_price_for_october_2026(self) -> None:
        # 0.1877 energy + network 63.1937 EUR/MWh + GSC 1.103 + WKK 0.364 c€/kWh
        # + the two statutory levies, VAT applied once.
        self.assertAlmostEqual(
            self.components().all_in_price(SCRAPED_ENERGY), 0.333868522, places=9
        )

    def test_it_reproduces_the_hand_written_helper_to_within_rounding(self) -> None:
        # The template helper this replaces used five constants rounded to four
        # decimals and was missing VAT on the energy term. Corrected, it gives
        # 0.333933; the parsed components give 0.333869. The 6e-5 gap is the
        # rounding in those constants, and is the regression check that we are
        # computing the same quantity.
        price = self.components().all_in_price(SCRAPED_ENERGY)
        self.assertAlmostEqual(price, 0.333933, delta=1e-4)

    def test_a_day_of_consumption_costs_what_the_invoice_would_say(self) -> None:
        price = self.components().all_in_price(SCRAPED_ENERGY)
        self.assertEqual(round(price * 3.689, 2), 1.23)

    def test_a_missing_component_is_refused(self) -> None:
        # A missing component does not make the price smaller, it makes it wrong.
        with self.assertRaises(tariffs.TariffError):
            tariffs.build(
                network=tariffs.parse_network_tariffs(
                    self.network_sheets, operator="Fluvius West"
                ),
                vtest={},
            )

    def test_a_different_vat_rate_flows_through(self) -> None:
        components = self.components(vat_rate=0.21)
        self.assertAlmostEqual(
            components.all_in_price(SCRAPED_ENERGY),
            (SCRAPED_ENERGY + components.total_excl_vat) * 1.21,
            places=9,
        )

    def test_fresh_components_are_not_stale(self) -> None:
        self.assertEqual(
            tariffs.stale_reasons(self.components(), today=date(2026, 10, 17)), ()
        )

    def test_an_old_vtest_month_is_stale(self) -> None:
        reasons = tariffs.stale_reasons(self.components(), today=date(2027, 1, 15))
        self.assertTrue(any("V-test" in reason for reason in reasons))

    def test_last_years_network_tariff_is_stale(self) -> None:
        reasons = tariffs.stale_reasons(self.components(), today=date(2027, 3, 1))
        self.assertTrue(any("nettarief" in reason.lower() for reason in reasons))

    def test_an_old_statutory_table_is_stale(self) -> None:
        reasons = tariffs.stale_reasons(self.components(), today=date(2028, 6, 1))
        self.assertTrue(any("heffing" in reason.lower() for reason in reasons))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — `module 'tariffs' has no attribute 'build'`.

- [ ] **Step 3: Implement assembly and staleness**

Append to `tariffs.py`:

```python
# How far behind a source may fall before the user is told. The V-test is
# published monthly and the current month's file appears during that month, so
# two months behind means a publication was missed, not that we are early.
MAX_VTEST_AGE_MONTHS = 2
# The statutory levies change by legislation; a year and a half without anyone
# checking is long enough to ask.
MAX_STATUTORY_AGE_MONTHS = 18


def build(
    *,
    network: Component,
    vtest: dict[str, Component],
    vat_rate: float = DEFAULT_VAT_RATE,
) -> TariffComponents:
    """Combine the parsed sources into one set of components.

    Raises rather than returning a partial set: an all-in price missing a
    component is not a low price, it is a wrong one.
    """
    components = (network, *vtest.values(), *statutory_components(vat_rate))
    present = frozenset(component.key for component in components)
    if missing := REQUIRED_KEYS - present:
        raise TariffError(f"Incomplete tariff components, missing {sorted(missing)}")
    return TariffComponents(components=components, vat_rate=vat_rate)


def _months_between(earlier: date, later: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def stale_reasons(components: TariffComponents, today: date) -> tuple[str, ...]:
    """Return a reason per source that has fallen behind, newest rule first."""
    reasons: list[str] = []
    by_key = {component.key: component for component in components.components}

    if (levy := by_key.get("gsc")) and _months_between(
        levy.valid_from, today
    ) > MAX_VTEST_AGE_MONTHS:
        reasons.append(
            f"The V-test figures are from {levy.valid_from:%B %Y} "
            f"({levy.source}); VREG publishes a new file every month."
        )

    network = by_key.get("network")
    if network and network.valid_until and network.valid_until < today:
        reasons.append(
            f"The distributienettarief expired on {network.valid_until:%d/%m/%Y} "
            f"({network.source}); VREG approves new tariffs every year."
        )

    statutory = [by_key[key] for key in ("excise", "energy_levy") if key in by_key]
    if statutory:
        newest = max(component.valid_from for component in statutory)
        if _months_between(newest, today) > MAX_STATUTORY_AGE_MONTHS:
            reasons.append(
                f"The bundled taksen en heffingen date from {newest:%B %Y} and "
                "are only updated by a release of this integration."
            )
    return tuple(reasons)
```

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 11 new tests, PASS (56 total).

- [ ] **Step 5: Commit**

```bash
git add custom_components/energiebe/tariffs.py tests/test_build.py
git commit -m "feat: assemble the all-in price and flag stale sources"
```

---

### Task 7: Discover and conditionally fetch the VREG assets

**Files:**
- Create: `custom_components/energiebe/vreg.py`
- Modify: `custom_components/energiebe/const.py`
- Create: `tests/fixtures/vreg-vtest-page.html`, `tests/fixtures/vreg-nettarieven-page.html`
- Create: `tests/test_vreg.py`

**Interfaces:**
- Consumes: `aiohttp.ClientSession` (duck-typed in tests), `read_xlsx`, `XlsxError`.
- Produces: `VregError`; `Asset(url, etag, last_modified, sheets)`; `find_asset_url(html, pattern) -> str`; `VTEST_PATTERN`, `NETWORK_PATTERN`; `async_load_asset(session, page_url, pattern, cached) -> Asset`.

Asset URLs embed a dated folder and a version suffix (`/2026-10/202610-v-test-data-exclbtw v2_0.xlsx`), so they are discovered on the page, never constructed. Both assets answer with `ETag` and `Last-Modified`, so each tick asks conditionally and parses only on a 200 — a handful of real parses a year instead of 365, and the 4 MB V-test download happens about monthly.

- [ ] **Step 1: Save the two page fixtures**

```bash
curl -sSL -o tests/fixtures/vreg-vtest-page.html \
  'https://www.vlaamsenutsregulator.be/cijfers/v-test-data-en-energieprijscurves'
curl -sSL -o tests/fixtures/vreg-nettarieven-page.html \
  'https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven'
grep -o 'https://assets[^"]*\.xlsx' tests/fixtures/vreg-vtest-page.html | head -3
```

Expected: at least one `assets.vlaamsenutsregulator.be/...v-test-data-exclbtw...xlsx` URL. If the pages are client-rendered and carry no such link, stop and report it: the discovery approach, not just this task, needs revisiting.

- [ ] **Step 2: Write the failing test**

```python
"""Discovering and conditionally fetching the VREG assets."""

import asyncio
import unittest

from loader import fixture, load

vreg = load("vreg")


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.status = status
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise AssertionError(f"unexpected raise_for_status in test: {self.status}")

    async def text(self) -> str:
        return self._body.decode()

    async def read(self) -> bytes:
        return self._body


class FakeSession:
    """Just enough of aiohttp.ClientSession to drive the fetcher."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, dict]] = []
        self.cookie_jar = self

    def clear_domain(self, domain: str) -> None:
        self.requests.append(("clear_domain", {"domain": domain}))

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((url, dict(kwargs)))
        return self._responses.pop(0)


class TestDiscovery(unittest.TestCase):
    def test_finds_the_vtest_asset_on_the_page(self) -> None:
        html = fixture("vreg-vtest-page.html").decode()
        url = vreg.find_asset_url(html, vreg.VTEST_PATTERN)
        self.assertIn("assets.vlaamsenutsregulator.be", url)
        self.assertTrue(url.endswith(".xlsx"))
        self.assertIn("v-test-data-exclbtw", url)

    def test_finds_the_network_asset_on_the_page(self) -> None:
        html = fixture("vreg-nettarieven-page.html").decode()
        url = vreg.find_asset_url(html, vreg.NETWORK_PATTERN)
        self.assertIn("istributienettarieven", url)
        self.assertTrue(url.endswith(".xlsx"))

    def test_the_newest_match_wins(self) -> None:
        html = (
            '<a href="https://assets.x/2025-10/202510-v-test-data-exclbtw.xlsx">old</a>'
            '<a href="https://assets.x/2026-10/202610-v-test-data-exclbtw v2_0.xlsx">new</a>'
        )
        self.assertIn("202610", vreg.find_asset_url(html, vreg.VTEST_PATTERN))

    def test_html_entities_in_the_href_are_decoded(self) -> None:
        html = '<a href="https://assets.x/2026-10/202610-v-test-data-exclbtw&amp;v2.xlsx">x</a>'
        self.assertNotIn("&amp;", vreg.find_asset_url(html, vreg.VTEST_PATTERN))

    def test_no_match_is_an_error(self) -> None:
        with self.assertRaises(vreg.VregError):
            vreg.find_asset_url("<html>nothing here</html>", vreg.VTEST_PATTERN)


class TestFetch(unittest.TestCase):
    def setUp(self) -> None:
        self.workbook = fixture("nettarieven-2026.xlsx")
        self.page = (
            '<a href="https://assets.x/2026-01/Distributienettarieven '
            'elektriciteit 2026.xlsx">download</a>'
        )

    def load(self, session: FakeSession, cached: object = None) -> object:
        return asyncio.run(
            vreg.async_load_asset(
                session,
                page_url="https://vreg.example/nettarieven",
                pattern=vreg.NETWORK_PATTERN,
                cached=cached,
            )
        )

    def test_a_first_fetch_parses_the_workbook(self) -> None:
        session = FakeSession(
            [
                FakeResponse(200, self.page.encode()),
                FakeResponse(
                    200,
                    self.workbook,
                    {"ETag": '"abc"', "Last-Modified": "Tue, 11 Nov 2025 10:00:00 GMT"},
                ),
            ]
        )
        asset = self.load(session)
        self.assertEqual(asset.etag, '"abc"')
        self.assertIn("ELEK Overzicht laagspanning", asset.sheets)

    def test_a_304_reuses_the_cached_sheets_without_parsing(self) -> None:
        first = FakeSession(
            [FakeResponse(200, self.page.encode()), FakeResponse(200, self.workbook, {"ETag": '"abc"'})]
        )
        cached = self.load(first)
        again = FakeSession([FakeResponse(200, self.page.encode()), FakeResponse(304)])
        asset = self.load(again, cached=cached)
        self.assertIs(asset.sheets, cached.sheets)
        headers = again.requests[-1][1]["headers"]
        self.assertEqual(headers["If-None-Match"], '"abc"')

    def test_affinity_cookies_are_shed_before_each_request(self) -> None:
        session = FakeSession(
            [FakeResponse(200, self.page.encode()), FakeResponse(200, self.workbook, {})]
        )
        self.load(session)
        cleared = [r for r in session.requests if r[0] == "clear_domain"]
        self.assertTrue(cleared)

    def test_a_server_error_is_an_error_not_a_silent_empty_asset(self) -> None:
        session = FakeSession([FakeResponse(200, self.page.encode()), FakeResponse(503)])
        with self.assertRaises(vreg.VregError):
            self.load(session)

    def test_a_body_that_is_not_a_workbook_is_an_error(self) -> None:
        session = FakeSession(
            [FakeResponse(200, self.page.encode()), FakeResponse(200, b"<html>oops</html>", {})]
        )
        with self.assertRaises(vreg.VregError):
            self.load(session)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests -v`
Expected: FAIL — no module `vreg`.

- [ ] **Step 4: Add the page URLs to `const.py`**

```python
# VREG publishes its spreadsheets at URLs that embed a dated folder and a
# version suffix, so the asset is found on the page rather than constructed.
VREG_VTEST_PAGE = (
    "https://www.vlaamsenutsregulator.be/cijfers/v-test-data-en-energieprijscurves"
)
VREG_NETWORK_PAGE = (
    "https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/"
    "hoeveel-bedragen-de-distributienettarieven"
)
```

- [ ] **Step 5: Implement the fetcher**

```python
"""Fetch the VREG spreadsheets the tariff components come from.

Two files, on very different schedules: the V-test is republished monthly, the
distribution network tariffs once a year. Both are linked from a plain
server-rendered page at a URL that embeds a dated folder and a version suffix,
so the link is read off the page instead of being guessed, and both answer with
``ETag``, so the daily tick asks conditionally and only parses on a 200.

Knows nothing about Home Assistant: it takes a session and returns parsed
sheets, which is what makes it testable without one.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp

from .xlsx import XlsxError, read_xlsx

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = aiohttp.ClientTimeout(total=60)

# The two assets, by the part of their file name that identifies them. Matching
# on the whole href keeps the dated folder out of our hands.
VTEST_PATTERN = re.compile(r"v-test-data-exclbtw", re.IGNORECASE)
NETWORK_PATTERN = re.compile(r"distributienettarieven\D*elektriciteit", re.IGNORECASE)

_HREF = re.compile(r'href="([^"]+\.xlsx[^"]*)"', re.IGNORECASE)


class VregError(Exception):
    """Raised when an asset cannot be found, fetched or read."""


@dataclass(frozen=True)
class Asset:
    """One fetched workbook, with what is needed to ask about it again."""

    url: str
    etag: str | None
    last_modified: str | None
    sheets: dict[str, list[list[str]]]


def find_asset_url(page: str, pattern: re.Pattern[str]) -> str:
    """Return the newest matching .xlsx link on a VREG page."""
    matches = [
        html.unescape(href) for href in _HREF.findall(page) if pattern.search(href)
    ]
    if not matches:
        raise VregError(f"No .xlsx link matching {pattern.pattern!r} on the page")
    # The dated folder sorts chronologically, so the highest string is newest.
    return max(matches)


async def _async_get(
    session: aiohttp.ClientSession, url: str, headers: dict[str, str] | None = None
) -> tuple[int, bytes, dict[str, str]]:
    """GET a URL, shedding any load-balancer affinity cookie first."""
    if host := urlparse(url).hostname:
        # Same hygiene as the tariff scrape: HA's session keeps cookies for the
        # life of the process, so one bad instance would otherwise stick.
        session.cookie_jar.clear_domain(host)
    try:
        async with session.get(url, headers=headers or {}, timeout=_TIMEOUT) as response:
            if response.status == 304:
                return 304, b"", dict(response.headers)
            if response.status >= 400:
                raise VregError(f"{url} answered {response.status}")
            return response.status, await response.read(), dict(response.headers)
    except (TimeoutError, aiohttp.ClientError) as err:
        raise VregError(f"Error fetching {url}: {err}") from err


async def async_load_asset(
    session: aiohttp.ClientSession,
    *,
    page_url: str,
    pattern: re.Pattern[str],
    cached: Asset | None = None,
) -> Asset:
    """Return the current workbook, reusing ``cached`` when it is unchanged."""
    _, body, _ = await _async_get(session, page_url)
    url = find_asset_url(body.decode(errors="replace"), pattern)

    headers: dict[str, str] = {}
    if cached is not None and cached.url == url:
        if cached.etag:
            headers["If-None-Match"] = cached.etag
        elif cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified

    status, data, response_headers = await _async_get(session, url, headers)
    if status == 304 and cached is not None:
        _LOGGER.debug("%s is unchanged", url)
        return cached

    try:
        sheets = read_xlsx(data)
    except XlsxError as err:
        raise VregError(f"{url} is not a workbook we can read: {err}") from err

    return Asset(
        url=url,
        etag=response_headers.get("ETag"),
        last_modified=response_headers.get("Last-Modified"),
        sheets=sheets,
    )
```

Note: `read_xlsx` on the 4 MB V-test takes long enough to matter on the event loop. The coordinator calls `async_load_asset` through `hass.async_add_executor_job`? It cannot — the function is async. Instead the coordinator passes the parsing off by awaiting this function and accepting the cost only when a 200 comes back (a handful of times a year); if profiling shows it blocking, split `async_load_asset` into fetch (async) and parse (executor) in a follow-up. Record this trade-off in the commit message.

- [ ] **Step 6: Run the tests and make sure they pass**

Run: `python3 -m unittest discover -s tests -v`
Expected: 10 new tests, PASS (66 total).

- [ ] **Step 7: Commit**

```bash
git add custom_components/energiebe/vreg.py custom_components/energiebe/const.py \
  tests/fixtures/vreg-vtest-page.html tests/fixtures/vreg-nettarieven-page.html \
  tests/test_vreg.py
git commit -m "feat: discover and conditionally fetch the VREG tariff spreadsheets"
```

---

### Task 8: Wire the components into the coordinator

**Files:**
- Modify: `custom_components/energiebe/const.py`
- Modify: `custom_components/energiebe/coordinator.py`

**Interfaces:**
- Consumes: `vreg.async_load_asset`, `tariffs.build`, `tariffs.parse_*`.
- Produces: `EnergieBeData.tariffs: TariffComponents | None`; `CONF_NETWORK_OPERATOR`, `CONF_METER_KIND`, `CONF_TARIFF_SCHEME`, `CONF_PRODUCT`, `CONF_VAT_RATE`, `DEFAULT_PRODUCT`, `SUPPLIER`.

This task and the three that follow touch Home Assistant APIs that are not importable here, so they carry no unit tests. They are deliberately thin — every decision they make was tested in Tasks 1–7 — and each ends with a live verification.

- [ ] **Step 1: Add the configuration keys to `const.py`**

```python
CONF_NETWORK_OPERATOR = "network_operator"
CONF_METER_KIND = "meter_kind"
CONF_TARIFF_SCHEME = "tariff_scheme"
CONF_PRODUCT = "product"
CONF_VAT_RATE = "vat_rate"

# The supplier whose tariffs this integration reads. A constant rather than an
# option: the scraped energy component is Energie.be's, so pairing it with
# another supplier's levies would be meaningless.
SUPPLIER = "Energie.be"
DEFAULT_PRODUCT = "Elektriciteit online"
```

- [ ] **Step 2: Add the field to `EnergieBeData`**

```python
@dataclass(frozen=True, kw_only=True)
class EnergieBeData:
    """Everything the sensors read from."""

    electricity: float
    gas_kwh: float
    injection: float
    gas_conversion_factor: float
    gas_conversion_source: str
    # None until the options needed to compute it are set, or while both the
    # fetch and the cache are empty. The five original sensors never depend on
    # it, so a VREG outage cannot take them down.
    tariffs: TariffComponents | None = None

    @property
    def gas_m3(self) -> float:
        """Gas price per cubic metre."""
        return self.gas_kwh * self.gas_conversion_factor
```

- [ ] **Step 3: Fetch and build in the coordinator**

Add to `EnergieBeCoordinator.__init__`:

```python
        self._vtest: Asset | None = None
        self._network: Asset | None = None
        self._tariffs: TariffComponents | None = None
```

Extend `_async_update_data`:

```python
    async def _async_update_data(self) -> EnergieBeData:
        """Scrape the tariffs and pair them with the current conversion factor."""
        prices = await self._async_scrape_prices()
        factor, source = await self._async_conversion_factor()
        return EnergieBeData(
            **prices,
            gas_conversion_factor=factor,
            gas_conversion_source=source,
            tariffs=await self._async_tariff_components(),
        )

    async def _async_tariff_components(self) -> TariffComponents | None:
        """Return the cost components on top of the energy price.

        Never fails the update. The scraped tariffs and the gas sensors do not
        depend on VREG, and taking five working sensors down because a regulator's
        web server was slow would be a worse outage than a stale all-in price --
        the same reasoning as the Atrias conversion factor above. A fetch that
        fails keeps the last known components; with nothing cached, the all-in
        sensor is simply unavailable.
        """
        operator = self.config_entry.options.get(CONF_NETWORK_OPERATOR)
        if not operator:
            return None

        try:
            self._vtest = await async_load_asset(
                self._session,
                page_url=VREG_VTEST_PAGE,
                pattern=VTEST_PATTERN,
                cached=self._vtest,
            )
            self._network = await async_load_asset(
                self._session,
                page_url=VREG_NETWORK_PAGE,
                pattern=NETWORK_PATTERN,
                cached=self._network,
            )
            options = self.config_entry.options
            self._tariffs = build(
                network=parse_network_tariffs(
                    self._network.sheets,
                    operator=operator,
                    meter_kind=options.get(CONF_METER_KIND, "digital"),
                    scheme=options.get(CONF_TARIFF_SCHEME, "single"),
                ),
                vtest=parse_vtest(
                    self._vtest.sheets,
                    supplier=SUPPLIER,
                    product=options.get(CONF_PRODUCT, DEFAULT_PRODUCT),
                    month=dt_util.now().date(),
                ),
                vat_rate=float(options.get(CONF_VAT_RATE, DEFAULT_VAT_RATE)),
            )
        except (VregError, TariffError) as err:
            _LOGGER.warning(
                "Could not refresh the tariff components: %s%s",
                err,
                " (keeping the last known values)" if self._tariffs else "",
            )

        return self._tariffs
```

Add the imports:

```python
from .const import (
    CONF_GOS_EAN,
    CONF_METER_KIND,
    CONF_NETWORK_OPERATOR,
    CONF_PRODUCT,
    CONF_TARIFF_SCHEME,
    CONF_VAT_RATE,
    DEFAULT_PRODUCT,
    DOMAIN,
    FALLBACK_GAS_CONVERSION_FACTOR,
    MAX_SCRAPE_ATTEMPTS,
    RETRY_INTERVAL,
    SUPPLIER,
    UPDATE_INTERVAL,
    URL,
    VREG_NETWORK_PAGE,
    VREG_VTEST_PAGE,
)
from .tariffs import (
    DEFAULT_VAT_RATE,
    TariffComponents,
    TariffError,
    build,
    parse_network_tariffs,
    parse_vtest,
)
from .vreg import NETWORK_PATTERN, VTEST_PATTERN, Asset, VregError, async_load_asset
```

- [ ] **Step 4: Check it still parses and the pure tests still pass**

```bash
python3 -m unittest discover -s tests -v
python3 - <<'PY'
import ast, pathlib
for name in ("coordinator", "const", "tariffs", "vreg", "xlsx"):
    ast.parse(pathlib.Path(f"custom_components/energiebe/{name}.py").read_text())
print("syntax ok")
PY
```

Expected: 66 tests PASS, `syntax ok`. (`ast.parse` on Python 3.11 rejects `coordinator.py`'s `type` alias; if so, check it on 3.12+ or rely on the hassfest run in step 6.)

- [ ] **Step 5: Commit**

```bash
git add custom_components/energiebe/const.py custom_components/energiebe/coordinator.py
git commit -m "feat: fetch and build the tariff components on the daily tick"
```

- [ ] **Step 6: Verify against a running Home Assistant**

Copy the integration into the instance (or install this branch through HACS), restart, and check:

```bash
# With a long-lived access token in $TOKEN and the instance at $HA
curl -s -H "Authorization: Bearer $TOKEN" "$HA/api/states/sensor.energie_be_electricity_price" | python3 -m json.tool
```

Expected: the five existing sensors still carry their values (the new code must not disturb them). The config entry has no `network_operator` yet, so no all-in price exists; that arrives in Task 9 and Task 10. Check the log for `Could not refresh the tariff components` — it must be absent, since the fetch is skipped without an operator.

---

### Task 9: Publish the all-in price sensor

**Files:**
- Modify: `custom_components/energiebe/sensor.py`

**Interfaces:**
- Consumes: `EnergieBeData.tariffs`, `TariffComponents.all_in_price`, `TariffComponents.as_attributes`.
- Produces: entity `sensor.energie_be_all_in_electricity_price`, unique id `<entry_id>_all_in`.

- [ ] **Step 1: Add the entity class**

```python
class EnergieBeAllInPriceSensor(
    CoordinatorEntity[EnergieBeCoordinator], SensorEntity
):
    """What a kWh actually costs: energy plus levies, network and taxes.

    Separate from the table-driven sensors above because it is the one entity
    that can be unavailable while the others are fine -- it needs components the
    regulator publishes, and a partial set must never be published as a price.
    """

    _attr_has_entity_name = True
    _attr_name = "All-in Electricity Price"
    _attr_native_unit_of_measurement = PRICE_PER_KWH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:cash-multiple"

    def __init__(self, coordinator: EnergieBeCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_all_in"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Energie.be",
            manufacturer="Energie.be",
            model="Public tariff page (unofficial)",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=URL,
        )

    @property
    def available(self) -> bool:
        """Only available with a full set of components to price with."""
        return super().available and self.coordinator.data.tariffs is not None

    @property
    def native_value(self) -> float | None:
        """Return the all-in price per kWh, VAT included."""
        data = self.coordinator.data
        if (components := data.tariffs) is None:
            return None
        return components.all_in_price(data.electricity)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return every component, its source, and its validity date."""
        data = self.coordinator.data
        if (components := data.tariffs) is None:
            return None
        return {
            **components.as_attributes(),
            "energy_component": data.electricity,
            "energy_component_source": URL,
        }
```

- [ ] **Step 2: Add it to the platform setup**

```python
async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergieBeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Energie.be sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(EnergieBeSensor(coordinator, description) for description in SENSORS),
            EnergieBeAllInPriceSensor(coordinator),
        ]
    )
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/energiebe/sensor.py
git commit -m "feat: publish an all-in electricity price sensor"
```

- [ ] **Step 4: Verify against a running Home Assistant**

Restart, then:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HA/api/states/sensor.energie_be_all_in_electricity_price" | python3 -m json.tool
```

Expected, with no network operator configured yet: `"state": "unavailable"`, and the five original sensors unaffected. The entity must exist — if it does not, the platform did not load; check the log.

---

### Task 10: Configure the components

**Files:**
- Modify: `custom_components/energiebe/config_flow.py`
- Modify: `custom_components/energiebe/strings.json`
- Modify: `custom_components/energiebe/translations/en.json`

**Interfaces:**
- Consumes: `vreg.async_load_asset`, `tariffs.network_operators`, `tariffs.vtest_products`, `METER_KINDS`, `TARIFF_SCHEMES`.
- Produces: options `network_operator`, `meter_kind`, `tariff_scheme`, `product`, `vat_rate`, alongside the existing `gos_ean`.

- [ ] **Step 1: Build the choices from the live files**

Following `_async_station_options`' pattern exactly: fetch, and if it cannot be fetched keep the form usable and say so in the log.

```python
async def _async_tariff_choices(
    hass: HomeAssistant,
) -> tuple[list[SelectOptionDict], list[SelectOptionDict]]:
    """Return the operator and product dropdowns VREG currently publishes."""
    session = async_get_clientsession(hass)
    operators: list[SelectOptionDict] = []
    products: list[SelectOptionDict] = []
    try:
        network = await async_load_asset(
            session, page_url=VREG_NETWORK_PAGE, pattern=NETWORK_PATTERN
        )
        operators = [
            SelectOptionDict(value=name, label=name)
            for name in network_operators(network.sheets)
        ]
        vtest = await async_load_asset(
            session, page_url=VREG_VTEST_PAGE, pattern=VTEST_PATTERN
        )
        products = [
            SelectOptionDict(value=name, label=name)
            for name in vtest_products(vtest.sheets, supplier=SUPPLIER)
        ]
    except (VregError, TariffError) as err:
        # The all-in sensor is optional; the gas station choice must not become
        # unreachable because VREG is down.
        _LOGGER.warning("Could not load the VREG tariff choices: %s", err)
    return operators, products
```

- [ ] **Step 2: Extend the options schema**

Replace `_schema` with a builder that keeps the station field first and adds the tariff fields only when their choices could be loaded:

```python
def _schema(
    stations: list[SelectOptionDict],
    operators: list[SelectOptionDict],
    products: list[SelectOptionDict],
    current: dict[str, Any],
) -> vol.Schema:
    """Build the options form: gas station first, then the all-in components."""
    fields: dict[Any, Any] = {
        vol.Required(
            CONF_GOS_EAN, default=current.get(CONF_GOS_EAN, AVERAGE)
        ): SelectSelector(
            SelectSelectorConfig(options=stations, mode=SelectSelectorMode.DROPDOWN)
        )
    }
    if operators:
        fields[
            vol.Optional(
                CONF_NETWORK_OPERATOR, default=current.get(CONF_NETWORK_OPERATOR, "")
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=[SelectOptionDict(value="", label="Not set"), *operators],
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        fields[
            vol.Optional(
                CONF_METER_KIND, default=current.get(CONF_METER_KIND, "digital")
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=sorted(METER_KINDS), translation_key="meter_kind",
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        fields[
            vol.Optional(
                CONF_TARIFF_SCHEME, default=current.get(CONF_TARIFF_SCHEME, "single")
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=sorted(TARIFF_SCHEMES), translation_key="tariff_scheme",
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
    if products:
        fields[
            vol.Optional(
                CONF_PRODUCT, default=current.get(CONF_PRODUCT, DEFAULT_PRODUCT)
            )
        ] = SelectSelector(
            SelectSelectorConfig(options=products, mode=SelectSelectorMode.DROPDOWN)
        )
    fields[
        vol.Optional(CONF_VAT_RATE, default=current.get(CONF_VAT_RATE, DEFAULT_VAT_RATE))
    ] = NumberSelector(
        NumberSelectorConfig(min=0, max=0.5, step=0.01, mode=NumberSelectorMode.BOX)
    )
    return vol.Schema(fields)
```

Both flows then pass their stored options as `current` and write every submitted key back, keeping `CONF_GOS_NAME` as they do today. The initial config flow keeps asking only for the station: an empty `network_operator` simply means no all-in sensor, which is the documented default.

- [ ] **Step 3: Add the strings**

In `strings.json` (and the same text in `translations/en.json`), under `options.step.init`:

```json
        "data": {
          "gos_ean": "Gas reception station (GOS)",
          "network_operator": "Distribution network operator",
          "meter_kind": "Meter",
          "tariff_scheme": "Tariff scheme",
          "product": "Energie.be product",
          "vat_rate": "VAT rate"
        },
        "data_description": {
          "network_operator": "Needed for the all-in electricity price. Flemish operators only — VREG does not publish tariffs for Brussels or Wallonia.",
          "meter_kind": "A digital meter and an analogue meter pay different distribution tariffs.",
          "tariff_scheme": "Which register your consumption is billed on.",
          "product": "Your Energie.be contract, as the VREG V-test names it.",
          "vat_rate": "0.06 for domestic electricity in Belgium."
        }
```

And a `selector` block for the two enumerations:

```json
  "selector": {
    "meter_kind": {
      "options": {
        "digital": "Digital meter",
        "classic": "Analogue meter"
      }
    },
    "tariff_scheme": {
      "options": {
        "single": "Single rate",
        "dual_day": "Dual rate — day",
        "dual_night": "Dual rate — night",
        "night_only": "Exclusive night"
      }
    }
  }
```

- [ ] **Step 4: Commit**

```bash
git add custom_components/energiebe/config_flow.py custom_components/energiebe/strings.json \
  custom_components/energiebe/translations/en.json
git commit -m "feat: let the user pick their network operator, meter and product"
```

- [ ] **Step 5: Verify against a running Home Assistant**

Restart, open **Settings → Devices & Services → Energie.be → Configure**, pick the operator (for the installation this was designed for: `Fluvius West`, digital, single rate, `Elektriciteit online`, 0.06), submit, and then:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$HA/api/states/sensor.energie_be_all_in_electricity_price" | python3 -m json.tool
```

Expected: a state of about `0.3339`, with `network`, `gsc`, `wkk`, `excise`, `energy_levy` and their `_source`/`_valid_from` attributes, `vat_rate: 0.06`, and `energy_component` equal to `sensor.energie_be_electricity_price`. If the state is `unavailable`, read the log line from `_async_tariff_components` — it names which source failed.

---

### Task 11: Tell the user when a source goes stale

**Files:**
- Modify: `custom_components/energiebe/coordinator.py`
- Modify: `custom_components/energiebe/strings.json`
- Modify: `custom_components/energiebe/translations/en.json`

**Interfaces:**
- Consumes: `tariffs.stale_reasons`.
- Produces: repair issue `energiebe/stale_tariffs`.

- [ ] **Step 1: Raise and clear the issue**

At the end of `_async_tariff_components`, after `self._tariffs` is set:

```python
        self._async_check_staleness()
        return self._tariffs

    def _async_check_staleness(self) -> None:
        """Raise a repair when a source has stopped being refreshed.

        Silence is the failure mode worth designing against here: a number that
        is two years old looks exactly like a number that is right.
        """
        if self._tariffs is None:
            return
        reasons = stale_reasons(self._tariffs, today=dt_util.now().date())
        if not reasons:
            async_delete_issue(self.hass, DOMAIN, _STALE_ISSUE)
            return
        async_create_issue(
            self.hass,
            DOMAIN,
            _STALE_ISSUE,
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key="stale_tariffs",
            translation_placeholders={"reasons": " ".join(reasons)},
        )
```

with, at module level:

```python
_STALE_ISSUE = "stale_tariffs"
```

and the import:

```python
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)
```

- [ ] **Step 2: Add the issue text**

In `strings.json` and `translations/en.json`:

```json
  "issues": {
    "stale_tariffs": {
      "title": "Energie.be tariff components are out of date",
      "description": "The all-in electricity price is being computed from figures that are no longer current, so it is probably wrong.\n\n{reasons}\n\nUpdating the integration usually fixes this. If it does not, open an issue — the bundled taxes and levies may need a new release."
    }
  }
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/energiebe/coordinator.py custom_components/energiebe/strings.json \
  custom_components/energiebe/translations/en.json
git commit -m "feat: raise a repair when the tariff sources go stale"
```

- [ ] **Step 4: Verify against a running Home Assistant**

Restart and confirm **Settings → System → Repairs** shows nothing for Energie.be with current files. To see the other branch, temporarily lower `MAX_VTEST_AGE_MONTHS` to `-1`, restart, confirm the repair appears with the V-test reason in it, then put it back and confirm the repair disappears by itself on the next refresh.

---

### Task 12: Document, migrate, release

**Files:**
- Modify: `README.md`
- Modify: `custom_components/energiebe/manifest.json`

- [ ] **Step 1: Document the sensor and the template that replaces the hardcoded helper**

Add to the README's feature table and a section after "Gas in €/m³":

```markdown
### All-in electricity price

`sensor.energie_be_electricity_price` is the energy component only — between a third and a half of what a kWh costs. Set your distribution network operator under **Configure** and the integration also publishes:

| Entity | Unit |
| --- | --- |
| `sensor.energie_be_all_in_electricity_price` | €/kWh |

That figure is the energy component plus the green-certificate and cogeneration levies (VREG V-test, monthly), your operator's distribution tariff (VREG, yearly) and the two statutory levies, with 6% VAT applied once. Every component, its source and its validity date are attributes of the sensor, so the number can always be taken apart.

A daily cost is then one template sensor:

```jinja
{{ (states('sensor.daily_electricity_import') | float(0)
    * states('sensor.energie_be_all_in_electricity_price') | float) | round(2) }}
```

Note the missing default on the price: `| float` without one makes the cost unavailable when the price is, rather than silently reporting a plausible, smaller, wrong number.

**What it excludes:** the capacity tariff (billed per kW of monthly peak), the data-management fee and your supplier's standing charge. Those are per-month and per-year amounts, not per-kWh, so they cannot be folded into a €/kWh figure. It is an estimate from public data, not a bill.

**Flanders only.** The operator list comes from VREG, which regulates the Flemish distribution network operators. Brussels (Sibelga) and Wallonia publish their tariffs elsewhere.
```

- [ ] **Step 2: Bump the version**

`manifest.json`: `"version": "1.1.0"` — a new entity and new options, no breaking change to the five existing ones.

- [ ] **Step 3: Run everything one more time**

```bash
python3 -m unittest discover -s tests -v
python3 -c "import json;[json.load(open(p)) for p in ('custom_components/energiebe/manifest.json','custom_components/energiebe/strings.json','custom_components/energiebe/translations/en.json')];print('json ok')"
```

Expected: 66 tests PASS, `json ok`.

- [ ] **Step 4: Commit, push, and let CI validate**

```bash
git add README.md custom_components/energiebe/manifest.json
git commit -m "docs: document the all-in electricity price and release 1.1.0"
git push -u origin HEAD
gh run watch
```

Expected: the HACS and hassfest jobs both pass. hassfest is the only check that reads `strings.json` and `manifest.json` the way Home Assistant does, so a red hassfest here means the JSON is wrong, not that CI is flaky.

- [ ] **Step 5: Release**

```bash
gh release create v1.1.0 --title "v1.1.0" --notes "All-in electricity price built from official VREG tariff components. See the README for the sensor and the cost template."
```

Then in Home Assistant: HACS → Energie.be → update → restart, configure the network operator, and replace the hardcoded template helper with the one-line template above.
