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
    DOMAIN,
    FALLBACK_GAS_CONVERSION_FACTOR,
)
from .coordinator import EnergieBeConfigEntry

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


def _schema(options: list[SelectOptionDict], default: str) -> vol.Schema:
    """Build the single-field form used by both flows."""
    return vol.Schema(
        {
            vol.Required(CONF_GOS_EAN, default=default): SelectSelector(
                SelectSelectorConfig(
                    options=options, mode=SelectSelectorMode.DROPDOWN
                )
            )
        }
    )


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
            step_id="user", data_schema=_schema(options, AVERAGE)
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
        """Let the user pick a different station."""
        options = await _async_station_options(self.hass)

        if user_input is not None:
            ean = user_input[CONF_GOS_EAN]
            return self.async_create_entry(
                data={
                    CONF_GOS_EAN: ean,
                    CONF_GOS_NAME: _label_for(options, ean),
                }
            )

        current = self.config_entry.options.get(CONF_GOS_EAN, AVERAGE)
        return self.async_show_form(
            step_id="init", data_schema=_schema(options, current)
        )
