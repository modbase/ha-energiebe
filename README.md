# Home Assistant — Energie.be Price Sensors

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)

This custom integration for [Home Assistant](https://www.home-assistant.io/) adds sensors that fetch the current energy prices from [Energie.be](https://energie.be).

> [!IMPORTANT]
> Unofficial integration, maintained by [@modbase](https://github.com/modbase). It is not affiliated with, endorsed by, or supported by Energie.be — it simply reads their public tariff page. Please report problems [here](https://github.com/modbase/ha-energiebe/issues) rather than to Energie.be.
>
> Prices are scraped from a web page, so they can break without warning if that page changes. Don't rely on them for billing.

## 📦 Features

- Scrapes the latest **electricity price**, **gas price**, and **injection price**
- Exposes them as sensor entities, grouped under a single **Energie.be** device:

  | Entity | Unit |
  | --- | --- |
  | `sensor.energie_be_electricity_price` | €/kWh |
  | `sensor.energie_be_all_in_electricity_price` | €/kWh |
  | `sensor.energie_be_injection_price` | €/kWh |
  | `sensor.energie_be_gas_price_eur_kwh` | €/kWh |
  | `sensor.energie_be_gas_price_eur_m3` | €/m³ |
  | `sensor.energie_be_gas_conversion_factor` | kWh/m³ |

- Refreshes **once a day** with a single request shared by all sensors, matching the monthly cadence at which the tariff is indexed (a failed fetch retries within 30 minutes rather than waiting for the next day)
- Records long-term statistics, so the prices show up in history and can be used in dashboards, automations, and the Energy panel

### Gas in €/m³

Energie.be quotes gas in c€/kWh, but Belgian meters read m³. The conversion depends on the calorific value of the gas at your reception station (GOS), which [Atrias](https://www.atrias.be/sector-data) publishes officially once a month — it varies slightly per station and drifts month to month.

Pick your station during setup and the integration tracks that value automatically; `sensor.energie_be_gas_conversion_factor` exposes the figure in use, with the station and source month as attributes. If you don't know your GOS, ask your grid operator, or leave it on the Belgian average — every active station currently sits within about 1% of it.

When Atrias can't be reached the €/m³ sensor falls back to that average rather than going unavailable, and the attribute says so.

### All-in electricity price

`sensor.energie_be_electricity_price` is the energy component only — between a third and a half of what a kWh costs. Set your distribution network operator under **Configure** and the integration also publishes `sensor.energie_be_all_in_electricity_price`.

That figure is the energy component plus the green-certificate and cogeneration levies ([VREG V-test](https://www.vlaamsenutsregulator.be/cijfers/v-test-data-en-energieprijscurves), monthly), your operator's distribution tariff ([VREG](https://www.vlaamsenutsregulator.be/elektriciteit-en-aardgas/nettarieven/hoeveel-bedragen-de-distributienettarieven), yearly) and the two statutory levies, with 6% VAT applied once. Every component, its source and its validity date are attributes of the sensor, so the number can always be taken apart. Both VREG files are fetched conditionally, so a 4 MB download happens about monthly rather than daily, and Home Assistant raises a repair if either source stops being refreshed.

A daily cost is then one template sensor:

```jinja
{{ (states('sensor.daily_electricity_import') | float(0)
    * states('sensor.energie_be_all_in_electricity_price') | float) | round(2) }}
```

Note the missing default on the price: `| float` without one makes the cost unavailable when the price is, rather than silently reporting a plausible, smaller, wrong number.

**What it excludes:** the capacity tariff (billed per kW of monthly peak), the data-management fee and your supplier's standing charge. Those are per-month and per-year amounts, not per-kWh, so they cannot be folded into a €/kWh figure. It is an estimate from public data, not a bill.

**Flanders only.** The operator list comes from VREG, which regulates the Flemish distribution network operators. Brussels (Sibelga) and Wallonia publish their tariffs elsewhere.

### Surviving the wrong page

Energie.be runs on Azure App Service, and its instances serve each other's cached renders: on any given request the tariff page may come back as the home page or a campaign page instead. The first response also sets an `ARRAffinity` cookie, which would otherwise pin Home Assistant to one instance for as long as it runs — so every retry would fetch the same wrong page. The integration drops that cookie and reasks until the tariff page arrives, up to eight times.

When even that fails — on 2026-10-17 the wrong-page rate reached 100% for about ten minutes — the last successful scrape is served instead, and `cached_at` appears as an attribute on the price sensors so a carried-forward value is always identifiable. The cache is kept on disk, so it survives a restart, and it expires when the month turns: the variable tariff is re-indexed monthly, so a price scraped in October is the October tariff for all of October and the wrong number in November. Once it expires the sensors go unavailable, as they did before.

## 📁 Installation

### HACS

This integration is not in the HACS default store, so add it as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/):

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=modbase&repository=ha-energiebe&category=integration)

1. HACS → ⋮ → **Custom repositories**
2. Repository: `https://github.com/modbase/ha-energiebe`, category: **Integration**
3. Download **Energie.be**, then restart Home Assistant

> [!NOTE]
> If you already have another `energiebe` integration installed through HACS, remove it first. Every copy installs to `config/custom_components/energiebe`, so only one can be present at a time.

### Manual

Copy the `custom_components/energiebe` directory into your Home Assistant `config/custom_components/` directory, then restart Home Assistant:

```bash
git clone https://github.com/modbase/ha-energiebe.git
cp -r ha-energiebe/custom_components/energiebe /path/to/config/custom_components/
```

## ⚙️ Configuration

Add the integration from **Settings → Devices & Services → Add Integration → Energie.be** and pick your gas reception station (GOS) from the list.

**Configure** on the integration card then offers the rest: your distribution network operator, whether you have a digital or an analogue meter, which tariff scheme your consumption is billed on, your Energie.be product and the VAT rate. Leave the operator unset and everything works as before, minus the all-in price sensor.

## 🙏 Credits

Originally written by [Fabian Meul](https://github.com/FabianMeul) as [FabianMeul/home-assistant-energie-be](https://github.com/FabianMeul/home-assistant-energie-be), and published here under the same MIT license with his copyright intact. This repository continues from that work with the Atrias gas conversion, the move to the `/nl/tarief` page, and the instance-affinity fix described above.
