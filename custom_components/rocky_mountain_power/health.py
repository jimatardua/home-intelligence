"""Pure, HA-independent staleness computation for the sync-health entities.

Deliberately has no `homeassistant` import, mirroring the same separation
`govee_collector/collector.py` keeps between its pure decision logic
(`compute_health_status`) and its asyncio/bleak-dependent code -- for the
same reason: it's what lets this logic be unit-tested directly (see
tests/test_health.py) without the real `homeassistant` package, which
isn't installed in this dev environment (see tests/test_api.py's
docstring for the full explanation of why that separation matters here).

Polling is daily (`UPDATE_INTERVAL` in const.py), so thresholds are set in
multiples of a day, not minutes:
- ok: less than one polling cycle plus a few hours' grace since the last
  success.
- stale: about one missed cycle -- still plausibly self-healing on its own
  next attempt.
- stuck: about two or more consecutive missed cycles. See
  docs/rmp-integration.md's "Real incident" section -- a poisoned login
  session once failed identically for 11 days with nothing visible
  anywhere; this threshold is meant to catch that on day 3, not day 11.
"""

from __future__ import annotations

from datetime import datetime, timedelta

HEALTH_STATUS_OK = "ok"
HEALTH_STATUS_STALE = "stale"
HEALTH_STATUS_STUCK = "stuck"

STALE_AFTER = timedelta(hours=30)
STUCK_AFTER = timedelta(hours=54)


def compute_sync_status(last_successful_sync: datetime | None, now: datetime) -> str:
    """"ok"/"stale"/"stuck" from how long it's been since the last success.

    `None` (never synced) is treated as "stuck" rather than "ok by
    default" -- in practice this is unreachable once entities exist, since
    `__init__.py` calls `async_config_entry_first_refresh()` before
    forwarding to the sensor/binary_sensor platforms, so a first-refresh
    failure blocks setup entirely rather than leaving entities behind with
    no successful sync yet. Kept as an explicit branch anyway, since
    silently treating "we don't actually know" as healthy is exactly the
    kind of gap this alert exists to close.
    """
    if last_successful_sync is None:
        return HEALTH_STATUS_STUCK
    age = now - last_successful_sync
    if age < STALE_AFTER:
        return HEALTH_STATUS_OK
    if age < STUCK_AFTER:
        return HEALTH_STATUS_STALE
    return HEALTH_STATUS_STUCK
