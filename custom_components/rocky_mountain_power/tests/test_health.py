"""Tests for health.py's ok/stale/stuck staleness thresholds.

health.py has zero `homeassistant` imports specifically so it can be
tested this directly -- but a plain `from custom_components.rocky_mountain_power
import health` would still execute the real `__init__.py` first (importing
a submodule always imports its parent package), which needs the real
`homeassistant` framework, not installed in this dev environment. So this
file uses the same synthetic-module-loading approach as test_api.py (see
that file's own docstring for the full explanation), loaded from its own
file path under a synthetic module name unrelated to the real
`custom_components.*` dotted path.

Run with the same invocation documented in test_api.py and
docs/rmp-integration.md:

    rmp/.venv/bin/python -m pytest custom_components/rocky_mountain_power/tests/ \\
        -q --import-mode=importlib --rootdir=custom_components/rocky_mountain_power/tests
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

_COMPONENT_DIR = Path(__file__).resolve().parent.parent
_STUB_PKG = "_rmp_under_test"


def _load_stub_submodule(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"{_STUB_PKG}.{name}", _COMPONENT_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _STUB_PKG
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


if f"{_STUB_PKG}.health" in sys.modules:
    _health = sys.modules[f"{_STUB_PKG}.health"]
else:
    if _STUB_PKG not in sys.modules:
        stub_pkg = types.ModuleType(_STUB_PKG)
        stub_pkg.__path__ = [str(_COMPONENT_DIR)]
        sys.modules[_STUB_PKG] = stub_pkg
    _health = _load_stub_submodule("health")

HEALTH_STATUS_OK = _health.HEALTH_STATUS_OK
HEALTH_STATUS_STALE = _health.HEALTH_STATUS_STALE
HEALTH_STATUS_STUCK = _health.HEALTH_STATUS_STUCK
STALE_AFTER = _health.STALE_AFTER
STUCK_AFTER = _health.STUCK_AFTER
compute_sync_status = _health.compute_sync_status

NOW = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)


def test_never_synced_is_stuck_not_ok():
    assert compute_sync_status(None, NOW) == HEALTH_STATUS_STUCK


def test_just_synced_is_ok():
    assert compute_sync_status(NOW - timedelta(minutes=1), NOW) == HEALTH_STATUS_OK


def test_just_under_stale_threshold_is_ok():
    assert compute_sync_status(NOW - (STALE_AFTER - timedelta(seconds=1)), NOW) == HEALTH_STATUS_OK


def test_exactly_at_stale_threshold_is_stale():
    assert compute_sync_status(NOW - STALE_AFTER, NOW) == HEALTH_STATUS_STALE


def test_just_under_stuck_threshold_is_stale():
    assert compute_sync_status(NOW - (STUCK_AFTER - timedelta(seconds=1)), NOW) == HEALTH_STATUS_STALE


def test_exactly_at_stuck_threshold_is_stuck():
    assert compute_sync_status(NOW - STUCK_AFTER, NOW) == HEALTH_STATUS_STUCK


def test_long_past_stuck_threshold_is_stuck():
    assert compute_sync_status(NOW - timedelta(days=11), NOW) == HEALTH_STATUS_STUCK
