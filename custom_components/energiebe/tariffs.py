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
