"""Thin wrapper around Home Assistant's REST API.

This is the first thing in this project that *writes* to Home Assistant --
every other package only ever reads the recorder database. The
`HA_TOKEN` env var (from `/etc/home-intelligence-control-panel.env`,
`chmod 600`, matching `/etc/govee-collector.env`'s existing convention)
never reaches the browser -- `server.py` is the only thing that ever sees
it, and this module is the only thing that ever sends it anywhere.

Two distinct exceptions rather than one, because the two failure modes
mean genuinely different things to show on the page: HA itself being
unreachable (confirmed this can really happen -- see
docs/hardware.md's domus section) versus HA being reachable but rejecting
or erroring on a specific request (e.g. the blind hub timing out, also
confirmed live -- see docs/control-panel.md).
"""

from __future__ import annotations

import os

import requests

from control_panel.const import HA_BASE_URL


class HomeAssistantUnreachable(Exception):
    """HA's API couldn't be reached at all (connection error/timeout)."""


class HomeAssistantError(Exception):
    """HA was reached but returned a non-2xx response."""


def _token() -> str:
    token = os.environ.get("HA_TOKEN")
    if not token:
        raise RuntimeError("HA_TOKEN is not set -- check /etc/home-intelligence-control-panel.env")
    return token


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def get_state(entity_id: str, *, timeout: float = 5.0) -> dict:
    """The current state + attributes for one entity."""
    try:
        resp = requests.get(f"{HA_BASE_URL}/api/states/{entity_id}", headers=_headers(), timeout=timeout)
    except requests.RequestException as err:
        raise HomeAssistantUnreachable(str(err)) from err
    if not resp.ok:
        raise HomeAssistantError(f"GET {entity_id} -> HTTP {resp.status_code}: {resp.text}")
    return resp.json()


def call_service(
    domain: str, service: str, entity_id: str | list[str], *, timeout: float = 10.0, **data
) -> None:
    """Calls `<domain>.<service>` against one or more entities.

    A blind-hub timeout or similar downstream hiccup surfaces as HA
    itself returning an error (HomeAssistantError), not a connection
    failure to HA (HomeAssistantUnreachable) -- HA is still reachable,
    it's the physical device behind it that didn't respond in time.
    """
    payload = {"entity_id": entity_id, **data}
    try:
        resp = requests.post(
            f"{HA_BASE_URL}/api/services/{domain}/{service}", headers=_headers(), json=payload, timeout=timeout
        )
    except requests.RequestException as err:
        raise HomeAssistantUnreachable(str(err)) from err
    if not resp.ok:
        raise HomeAssistantError(f"{domain}.{service} -> HTTP {resp.status_code}: {resp.text}")
