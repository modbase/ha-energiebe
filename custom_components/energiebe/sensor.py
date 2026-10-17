"""Sensor platform for the Energie.be integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, URL
from .coordinator import EnergieBeConfigEntry, EnergieBeCoordinator, EnergieBeData

PRICE_PER_KWH = f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}"
PRICE_PER_CUBIC_METER = f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}"
KWH_PER_CUBIC_METER = f"{UnitOfEnergy.KILO_WATT_HOUR}/{UnitOfVolume.CUBIC_METERS}"


@dataclass(frozen=True, kw_only=True)
class EnergieBeSensorEntityDescription(SensorEntityDescription):
    """Describes an Energie.be sensor entity."""

    value_fn: Callable[[EnergieBeData], float]
    attributes_fn: Callable[[EnergieBeData], dict[str, Any]] | None = None


SENSORS: tuple[EnergieBeSensorEntityDescription, ...] = (
    EnergieBeSensorEntityDescription(
        key="electricity",
        name="Electricity Price",
        native_unit_of_measurement=PRICE_PER_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:cash",
        value_fn=lambda data: data.electricity,
    ),
    EnergieBeSensorEntityDescription(
        key="injection",
        name="Injection Price",
        native_unit_of_measurement=PRICE_PER_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:cash",
        value_fn=lambda data: data.injection,
    ),
    EnergieBeSensorEntityDescription(
        key="gas_kwh",
        name=f"Gas Price ({PRICE_PER_KWH})",
        native_unit_of_measurement=PRICE_PER_KWH,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:cash",
        value_fn=lambda data: data.gas_kwh,
    ),
    EnergieBeSensorEntityDescription(
        key="gas_m3",
        name=f"Gas Price ({PRICE_PER_CUBIC_METER})",
        native_unit_of_measurement=PRICE_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:cash",
        value_fn=lambda data: data.gas_m3,
        attributes_fn=lambda data: {"conversion_source": data.gas_conversion_source},
    ),
    EnergieBeSensorEntityDescription(
        key="gas_conversion_factor",
        name="Gas Conversion Factor",
        native_unit_of_measurement=KWH_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        icon="mdi:swap-horizontal",
        value_fn=lambda data: data.gas_conversion_factor,
        attributes_fn=lambda data: {"source": data.gas_conversion_source},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EnergieBeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Energie.be sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        EnergieBeSensor(coordinator, description) for description in SENSORS
    )


class EnergieBeSensor(CoordinatorEntity[EnergieBeCoordinator], SensorEntity):
    """A single tariff published by Energie.be."""

    _attr_has_entity_name = True
    entity_description: EnergieBeSensorEntityDescription

    def __init__(
        self,
        coordinator: EnergieBeCoordinator,
        description: EnergieBeSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="Energie.be",
            # manufacturer names where the data comes from, not who wrote this.
            # The model spells out that the integration is not theirs, since the
            # UI renders the manufacturer as "by Energie.be".
            manufacturer="Energie.be",
            model="Public tariff page (unofficial)",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=URL,
        )

    @property
    def native_value(self) -> float:
        """Return the most recently scraped value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return where the conversion factor came from, where relevant."""
        if (attributes_fn := self.entity_description.attributes_fn) is None:
            return None
        return attributes_fn(self.coordinator.data)
