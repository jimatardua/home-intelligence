# NOTICE

This integration is forked from
[zestysoft/sensus_analytics_integration](https://github.com/zestysoft/sensus_analytics_integration),
licensed under the Apache License, Version 2.0 (see `LICENSE` in this
directory). Copyright belongs to its original author(s).

## Changes made in this fork

Full detail in `docs/sensus-analytics-water.md` in this repository. Summary:

1. **Security/UX**: the password field in both the setup and options forms
   now uses Home Assistant's masked `TextSelector` instead of a plain
   `str` field. The original options flow also pre-filled the real
   password back into that same unmasked field as its visible default;
   the options flow now re-validates credentials the same way initial
   setup does, instead of writing unvalidated data straight to the
   config entry.
2. **DRY**: the same login call was implemented twice upstream (once via
   `aiohttp` in `config_flow.py`, once via `requests` in
   `coordinator.py`), against the same endpoint with the same payload.
   Consolidated into one `api.py` module (`SensusAnalyticsClient`), the
   only place either file now makes an HTTP request. Two smaller
   duplications found while porting the code over -- the tiered-pricing
   math repeated (with one small difference) across two sensor classes,
   and four "last hour" sensors each independently re-implementing the
   same hour-matching search loop -- were also factored into shared
   helpers in `sensor.py`.
3. **Dead code removed**: a `is_matching()` config-flow override that
   unconditionally `return False`d with a "implement if necessary"
   comment -- never actually invoked, since this integration has no
   discovery source, only a user-initiated flow.
4. **Modernized to `entry.runtime_data`** (current HA convention) instead
   of the `hass.data[DOMAIN][entry.entry_id]` dict pattern, matching
   `custom_components/rocky_mountain_power` elsewhere in this repo. As a
   side effect, changing credentials via the options flow now actually
   takes effect (a full reload) -- the original options flow called
   `coordinator.async_request_refresh()` on the *existing* coordinator,
   which kept using its already-constructed client and old credentials.
5. **Tests added** -- none existed upstream.
6. `update_interval` moved to a named, documented constant, default
   changed from 5 minutes to 30 (Sensus Analytics is documented to update
   far less often than every 5 minutes; the real cadence for this
   specific utility is unconfirmed as of this writing).

Not changed: the core API surface (login endpoint, daily/hourly data
endpoints, JSON response parsing), the sensor entity set, and the
config-schema fields (credentials + billing-tier pricing still share one
flat schema, matching upstream -- see "Deferred" in
docs/sensus-analytics-water.md for why that wasn't split apart here).
