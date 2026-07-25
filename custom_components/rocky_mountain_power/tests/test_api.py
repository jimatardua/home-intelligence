"""Tests for api.py's session-invalidation/self-healing behavior.

Focused on the real incident this hardening was built from: RMP's
SelfAsserted login endpoint rejected fully correct, unchanged credentials
for 11 straight days on a single long-lived session, because
`_invalidate_session()` only set a `force_relogin` flag rather than
actually discarding the session -- every subsequent daily poll kept
retrying on the same poisoned session and failing identically. A manual
Home Assistant integration reload (which does build a genuinely fresh
session) fixed it immediately with the same credentials, confirming the
session object -- not the credentials -- was the problem.

Pure mocking of `requests.Session`, no network calls, no real credentials.
This is deliberately separate from `rmp/test_api.py`, which exercises the
real live API by hand with real credentials from a `.env` file -- a manual
verification tool, not something the automated suite should ever touch.

api.py and const.py are plain, HA-independent Python (see api.py's module
docstring), but a normal `from custom_components.rocky_mountain_power
import api` would still execute the package's real `__init__.py` first
(importing a submodule always imports its parent package), which needs
the real `homeassistant` framework -- not installed in this dev
environment, and not needed to test session logic that never touches HA
at all. So api.py/const.py are loaded directly from their file paths under
a synthetic module name that has no relationship to the real
`custom_components.*` dotted path, entirely sidestepping both the real
`__init__.py` and pytest's own package-name resolution for this test file.

That resolution still trips over the real `__init__.py` if pytest's
rootdir is left to auto-detect upward from repo root (it walks up looking
for `__init__.py` boundaries when computing this file's dotted module
name, regardless of `--import-mode`) -- so `--rootdir` must be pinned to
this `tests/` directory explicitly:

    rmp/.venv/bin/python -m pytest custom_components/rocky_mountain_power/tests/ \\
        -q --import-mode=importlib --rootdir=custom_components/rocky_mountain_power/tests

Uses `rmp/.venv` (already has `requests`/`cryptography` installed, since
it's the same environment `rmp/test_api.py` uses) rather than a new
dedicated venv for this component -- `pytest` was added to it for this.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_COMPONENT_DIR = Path(__file__).resolve().parent.parent
_STUB_PKG = "_rmp_under_test"


def _load_stub_submodule(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"{_STUB_PKG}.{name}", _COMPONENT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _STUB_PKG
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if _STUB_PKG not in sys.modules:
    stub_pkg = types.ModuleType(_STUB_PKG)
    stub_pkg.__path__ = [str(_COMPONENT_DIR)]
    sys.modules[_STUB_PKG] = stub_pkg
    _load_stub_submodule("const")
    _api = _load_stub_submodule("api")
else:
    _api = sys.modules[f"{_STUB_PKG}.api"]

InvalidAuth = _api.InvalidAuth
CannotConnect = _api.CannotConnect
RockyMountainPowerClient = _api.RockyMountainPowerClient

# A minimal, real-shaped B2C login page body -- just enough for
# parse_settings() to extract a csrf token and transaction id.
SETTINGS_HTML = 'var SETTINGS = {"csrf": "fake-csrf", "transId": "fake-trans"};'

# The exact JSON body observed live from RMP's SelfAsserted endpoint when it
# rejected a login on a stale session -- HTTP 200 with a nested "status" of
# "400", not an HTTP-level error (that's how Azure B2C's SelfAsserted step
# actually reports a rejected credential/session, confirmed against the
# real incident's logs).
SELF_ASSERTED_REJECTION = {
    "status": "400",
    "errorCode": "AADB2C90278",
    "message": "Unable to validate the information provided.",
}


def _mock_response(status_code: int = 200, text: str = "", json_data: dict | None = None, url: str = "https://example.com"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.url = url
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no json body")
    return resp


def _rejecting_session() -> MagicMock:
    """A mock requests.Session whose login attempt fails exactly like the
    real incident: the login page loads fine, but SelfAsserted rejects the
    (in reality, perfectly valid) credentials."""
    session = MagicMock()
    session.get.return_value = _mock_response(text=SETTINGS_HTML)
    session.post.return_value = _mock_response(json_data=SELF_ASSERTED_REJECTION)
    return session


def test_invalidate_session_replaces_the_session_object():
    # The bug this guards against: an earlier version only set a flag and
    # kept the exact same Session (and its cookie jar) around forever.
    client = RockyMountainPowerClient("user", "pass")
    old_session = client._session
    client._invalidate_session()
    assert client._session is not old_session


def test_invalidate_session_resets_crypto_cached_agreement_and_auth():
    client = RockyMountainPowerClient("user", "pass")
    client._crypto = object()
    client._cached_agreement = object()
    client._auth.authenticated = True

    client._invalidate_session()

    assert client._crypto is None
    assert client._cached_agreement is None
    assert client._auth.authenticated is False


def test_rejected_login_discards_the_session_it_failed_on():
    client = RockyMountainPowerClient("user", "pass")
    rejecting_session = _rejecting_session()
    client._session = rejecting_session

    with pytest.raises(InvalidAuth):
        client._login()

    # The session that just failed must not still be the client's session
    # -- reusing it would mean every future attempt fails identically.
    assert client._session is not rejecting_session
    assert client._auth.authenticated is False


def test_ensure_authenticated_attempts_a_fresh_login_on_the_next_call():
    """End-to-end at the actual gate every API method calls: simulates two
    consecutive daily polls. The first fails and must discard its session;
    the second (the next scheduled poll) must still attempt to log in
    again -- not silently treat the client as authenticated, and not reuse
    the discarded session from the first attempt.
    """
    client = RockyMountainPowerClient("user", "pass")
    rejecting_session = _rejecting_session()
    client._session = rejecting_session

    with pytest.raises(InvalidAuth):
        client.ensure_authenticated()

    assert client._session is not rejecting_session

    with patch.object(client, "_login") as mock_login:
        client.ensure_authenticated()
        mock_login.assert_called_once()


def test_network_error_during_login_also_discards_the_session():
    import requests

    client = RockyMountainPowerClient("user", "pass")
    broken_session = MagicMock()
    broken_session.get.side_effect = requests.ConnectionError("boom")
    client._session = broken_session

    with pytest.raises(CannotConnect):
        client._login()

    assert client._session is not broken_session
