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

import re
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
_VALIDITY = re.compile(
    r"geldt van (\d{2})/(\d{2})/(\d{4}) t\.e\.m\. (\d{2})/(\d{2})/(\d{4})"
)

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
        raise TariffError(
            f"Unknown operator {operator!r}; the file has {sorted(columns)}"
        )

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
            source=(
                f"VREG distributienettarieven {valid_from.year}, "
                f"{wanted}, {block_label}"
            ),
            valid_from=valid_from,
            valid_until=valid_until,
        )

    raise TariffError(
        f"No {row_label!r} row in the {block_label!r} {_EXCL_VAT} block"
    )


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


def statutory_components(vat_rate: float = DEFAULT_VAT_RATE) -> tuple[Component, ...]:
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
