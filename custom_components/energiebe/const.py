"""Constants for the Energie.be integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "energiebe"

URL = "https://energie.be/nl/tarief"

# Atrias publishes the official Belgian gross calorific values per GOS (gas
# reception station), one file per month. See atrias.py for the details.
ATRIAS_RUNTIME_CONFIG_URL = "https://www.atrias.be/runtime-config.js"
ATRIAS_GCV_URL = (
    "https://api.atrias.be/roots/download/"
    "SectorData%2F02%20Gross%20Calorific%20Values%2F{year}%2FGCV{year}{month:02d}.txt"
)

# Rough mean across the active Belgian stations, which span about 11.39-11.62.
# Only used when no station is configured or Atrias cannot be reached.
FALLBACK_GAS_CONVERSION_FACTOR = 11.54

CONF_GOS_EAN = "gos_ean"
CONF_GOS_NAME = "gos_name"

# energie.be indexes its variable tariff monthly, so there is nothing to gain
# from polling harder than once a day.
UPDATE_INTERVAL = timedelta(days=1)

# energie.be runs on Azure App Service, which hands out an ARRAffinity cookie
# pinning a client to one instance, and the instances serve each other's cached
# renders: a given instance may answer /nl/tarief with the home page, the
# "pro actief" campaign page or an asset stub. Measured 2026-10-17: only about a
# third of the instances answer with the real tariff page, and once the cookie
# pins us to a bad one every retry returns that same wrong page. So drop the
# affinity cookie and reroll until the page we asked for arrives -- eight tries
# puts the odds of coming away empty-handed near zero.
MAX_SCRAPE_ATTEMPTS = 8

# A transient failure should not leave the sensors unavailable until tomorrow,
# so network errors ask the coordinator to come back sooner. Failures that are
# not transient -- markup we cannot parse -- deliberately wait for the next
# daily slot instead, since retrying them quickly would only add noise.
RETRY_INTERVAL = timedelta(minutes=30)
