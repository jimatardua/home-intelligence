"""Diagnostics support for Rocky Mountain Power."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import RockyMountainPowerConfigEntry

TO_REDACT = {
    "site_idn",
    "service_sequence",
    "account_sequence",
    "agreement_sequence",
    "customer_idn",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RockyMountainPowerConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    site_bundle_signature doubles as an early-warning canary: if it changes
    between polls, RMP shipped a new frontend build, which is exactly the
    kind of change that could silently break parse_settings() or the
    request-encryption contract.
    """
    coordinator = entry.runtime_data
    client = coordinator.client
    agreement = client.cached_agreement

    return async_redact_data(
        {
            "authenticated": client.is_authenticated,
            "last_successful_sync": (
                coordinator.last_successful_sync.isoformat()
                if coordinator.last_successful_sync
                else None
            ),
            "last_poll_duration_seconds": coordinator.last_poll_duration_seconds,
            "latest_interval_date": (
                coordinator.latest_interval_date.isoformat()
                if coordinator.latest_interval_date
                else None
            ),
            "site_bundle_signature": client.site_bundle_signature,
            "agreement_ids": asdict(agreement) if agreement else None,
        },
        TO_REDACT,
    )
