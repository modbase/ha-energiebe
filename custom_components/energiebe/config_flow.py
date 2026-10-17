"""Config and options flow for the Energie.be integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import dt as dt_util

from .atrias import AtriasError, async_fetch_gcv, create_ssl_context
from .const import (
    CONF_GOS_EAN,
    CONF_GOS_NAME,
    CONF_METER_KIND,
    CONF_NETWORK_OPERATOR,
    CONF_PRODUCT,
    CONF_TARIFF_SCHEME,
    CONF_VAT_RATE,
    DEFAULT_PRODUCT,
    DOMAIN,
    FALLBACK_GAS_CONVERSION_FACTOR,
    SUPPLIER,
    VREG_NETWORK_PAGE,
    VREG_VTEST_PAGE,
)
from .coordinator import EnergieBeConfigEntry
from .tariffs import (
    DEFAULT_VAT_RATE,
    METER_KINDS,
    TARIFF_SCHEMES,
    TariffError,
    network_operators,
    vtest_products,
)
from .vreg import NETWORK_PATTERN, VTEST_PATTERN, VregError, async_load_asset

_LOGGER = logging.getLogger(__name__)

# Sentinel for "don't pin a station, use the national average".
AVERAGE = ""


async def _async_station_options(hass: HomeAssistant) -> list[SelectOptionDict]:
    """Build the station dropdown from the values Atrias currently publishes."""
    options = [
        SelectOptionDict(
            value=AVERAGE,
            label=(
                f"Belgian average ({FALLBACK_GAS_CONVERSION_FACTOR:.2f} kWh/m³)"
            ),
        )
    ]

    session = async_get_clientsession(hass)
    try:
        ssl_context = await hass.async_add_executor_job(create_ssl_context)
        report = await async_fetch_gcv(session, ssl_context, dt_util.now().date())
    except AtriasError as err:
        # Setting up without a station is fine, it just falls back to the average.
        _LOGGER.warning("Could not load the Atrias station list: %s", err)
        return options

    options.extend(
        SelectOptionDict(
            value=station.ean,
            label=f"{station.name} ({station.value:.3f} kWh/m³)",
        )
        for station in sorted(report.stations, key=lambda station: station.name)
    )
    return options


def _station_field(
    options: list[SelectOptionDict], default: str
) -> dict[Any, Any]:
    """The gas station dropdown, the one field initial setup asks for."""
    return {
        vol.Required(CONF_GOS_EAN, default=default): SelectSelector(
            SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)
        )
    }


def _station_schema(options: list[SelectOptionDict], default: str) -> vol.Schema:
    """Build the single-field form initial setup shows."""
    return vol.Schema(_station_field(options, default))


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


def _schema(
    stations: list[SelectOptionDict],
    operators: list[SelectOptionDict],
    products: list[SelectOptionDict],
    current: dict[str, Any],
) -> vol.Schema:
    """Build the options form: gas station first, then the all-in components."""
    fields: dict[Any, Any] = _station_field(
        stations, current.get(CONF_GOS_EAN, AVERAGE)
    )
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
                options=sorted(METER_KINDS),
                translation_key="meter_kind",
                mode=SelectSelectorMode.DROPDOWN,
            )
        )
        fields[
            vol.Optional(
                CONF_TARIFF_SCHEME, default=current.get(CONF_TARIFF_SCHEME, "single")
            )
        ] = SelectSelector(
            SelectSelectorConfig(
                options=sorted(TARIFF_SCHEMES),
                translation_key="tariff_scheme",
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
        vol.Optional(
            CONF_VAT_RATE, default=current.get(CONF_VAT_RATE, DEFAULT_VAT_RATE)
        )
    ] = NumberSelector(
        NumberSelectorConfig(min=0, max=0.5, step=0.01, mode=NumberSelectorMode.BOX)
    )
    return vol.Schema(fields)


def _label_for(options: list[SelectOptionDict], ean: str) -> str:
    """Return the station name stored alongside the EAN, for display."""
    for option in options:
        if option["value"] == ean:
            # Strip the trailing " (11.484 kWh/m³)" the dropdown shows.
            return option["label"].rsplit(" (", 1)[0]
    return ""


class EnergieBeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask which gas reception station the meter hangs off."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        options = await _async_station_options(self.hass)

        if user_input is not None:
            ean = user_input[CONF_GOS_EAN]
            return self.async_create_entry(
                title="Energie.be",
                data={},
                options={
                    CONF_GOS_EAN: ean,
                    CONF_GOS_NAME: _label_for(options, ean),
                },
            )

        return self.async_show_form(
            step_id="user", data_schema=_station_schema(options, AVERAGE)
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: EnergieBeConfigEntry) -> EnergieBeOptionsFlow:
        """Return the options flow."""
        return EnergieBeOptionsFlow()


class EnergieBeOptionsFlow(OptionsFlow):
    """Allow the station to be changed after setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change the station and the all-in price components."""
        stations = await _async_station_options(self.hass)
        operators, products = await _async_tariff_choices(self.hass)

        if user_input is not None:
            ean = user_input[CONF_GOS_EAN]
            return self.async_create_entry(
                data={
                    **user_input,
                    CONF_GOS_NAME: _label_for(stations, ean),
                }
            )

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                stations, operators, products, dict(self.config_entry.options)
            ),
        )
