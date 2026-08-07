"""Home Assistant MQTT-discovery config for the 3 Govee sensors.

Pure functions -- no MQTT/network I/O -- so the discovery payload shape is
unit-testable without a broker or hardware. `collector.py` publishes exactly
what this module builds; nothing here talks to paho-mqtt or bleak directly.

Each of the 3 physical sensors becomes one HA "device" (grouped via the
`device` block below) with 4 entities: temperature, humidity, battery,
signal strength. Every payload sets an explicit `object_id`, but confirmed
live that HA does NOT actually use it for entity-ID generation when a
`device` block + `has_entity_name: true` are both present (as they are
here) -- it instead derives the entity ID from the combined device+entity
display name, e.g. `sensor.wineador_th01_temperature`, not the shorter
`sensor.wineador_temperature` this module's `object_id` field requests.
`object_id` is left in place anyway (harmless, and correct per the
discovery spec even if this HA version doesn't act on it for this entity
shape) but `cigar_dashboard/govee_history.py` targets the real, verified
entity IDs, not this field's value -- don't assume the two match without
checking live if this module ever changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from govee_collector.decode import DEVICE_LABELS

DISCOVERY_PREFIX = "homeassistant"
STATUS_TOPIC = "govee/collector/status"

STATUS_PAYLOAD_AVAILABLE = "online"
STATUS_PAYLOAD_NOT_AVAILABLE = "offline"

# H5075s broadcast every few seconds, so 5 minutes of silence already means
# something's wrong (dead battery, out of range, BLE issue) -- a starting
# point per the plan, not a fixed requirement; widen if live testing shows
# false-positive staleness from ordinary publish-cadence jitter.
EXPIRE_AFTER_SECONDS = 300


@dataclass(frozen=True)
class MetricSpec:
    value_json_key: str
    object_id_suffix: str
    name: str
    unit: str
    device_class: str


METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("temp_f", "temperature", "Temperature", "°F", "temperature"),
    MetricSpec("humidity_pct", "humidity", "Humidity", "%", "humidity"),
    MetricSpec("battery_pct", "battery", "Battery", "%", "battery"),
    MetricSpec("rssi", "rssi", "Signal Strength", "dBm", "signal_strength"),
)


def state_topic(device_id: str) -> str:
    return f"govee/{device_id}/state"


def _device_key(device_id: str) -> str:
    return f"govee_{device_id.lower()}"


def discovery_topic(device_id: str, metric: MetricSpec) -> str:
    return f"{DISCOVERY_PREFIX}/sensor/{_device_key(device_id)}/{metric.object_id_suffix}/config"


def discovery_payload(device_id: str, metric: MetricSpec) -> dict:
    label = DEVICE_LABELS[device_id]
    device_key = _device_key(device_id)
    return {
        "name": metric.name,
        "object_id": f"{label.lower()}_{metric.object_id_suffix}",
        "unique_id": f"{device_key}_{metric.object_id_suffix}",
        "state_topic": state_topic(device_id),
        "value_template": f"{{{{ value_json.{metric.value_json_key} }}}}",
        "unit_of_measurement": metric.unit,
        "device_class": metric.device_class,
        "state_class": "measurement",
        "expire_after": EXPIRE_AFTER_SECONDS,
        "qos": 1,
        "availability_topic": STATUS_TOPIC,
        "payload_available": STATUS_PAYLOAD_AVAILABLE,
        "payload_not_available": STATUS_PAYLOAD_NOT_AVAILABLE,
        "has_entity_name": True,
        "device": {
            "identifiers": [device_key],
            "name": f"{label} ({device_id})",
            "manufacturer": "Govee",
            "model": "H5075",
        },
    }


def all_discovery_messages() -> list[tuple[str, dict]]:
    """(topic, payload) for every entity across all known devices."""
    return [
        (discovery_topic(device_id, metric), discovery_payload(device_id, metric))
        for device_id in DEVICE_LABELS
        for metric in METRICS
    ]
