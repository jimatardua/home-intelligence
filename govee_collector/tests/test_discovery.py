from __future__ import annotations

from govee_collector.decode import DEVICE_LABELS
from govee_collector.discovery import (
    EXPIRE_AFTER_SECONDS,
    METRICS,
    STATUS_TOPIC,
    all_discovery_messages,
    discovery_payload,
    discovery_topic,
    state_topic,
)


def test_all_discovery_messages_covers_every_device_and_metric():
    messages = all_discovery_messages()

    assert len(messages) == len(DEVICE_LABELS) * len(METRICS)


def test_discovery_topics_are_unique():
    topics = [topic for topic, _ in all_discovery_messages()]

    assert len(topics) == len(set(topics))


def test_discovery_topic_shape():
    metric = METRICS[0]  # temperature

    topic = discovery_topic("TH01", metric)

    assert topic == "homeassistant/sensor/govee_th01/temperature/config"


def test_discovery_payload_groups_under_one_device_per_sensor():
    for metric in METRICS:
        payload = discovery_payload("TH01", metric)
        assert payload["device"]["identifiers"] == ["govee_th01"]
        assert payload["device"]["name"] == "Wineador (TH01)"
        assert payload["device"]["manufacturer"] == "Govee"
        assert payload["device"]["model"] == "H5075"


def test_discovery_payload_has_deterministic_object_id():
    temp_payload = discovery_payload("TH02", METRICS[0])
    humidity_payload = discovery_payload("TH02", METRICS[1])

    assert temp_payload["object_id"] == "drybox_temperature"
    assert humidity_payload["object_id"] == "drybox_humidity"


def test_discovery_payload_unique_id_is_stable_and_distinct_across_devices():
    th01 = discovery_payload("TH01", METRICS[0])
    th02 = discovery_payload("TH02", METRICS[0])

    assert th01["unique_id"] == "govee_th01_temperature"
    assert th02["unique_id"] == "govee_th02_temperature"
    assert th01["unique_id"] != th02["unique_id"]


def test_discovery_payload_value_template_references_correct_json_key():
    for metric in METRICS:
        payload = discovery_payload("TH03", metric)
        assert payload["value_template"] == f"{{{{ value_json.{metric.value_json_key} }}}}"


def test_discovery_payload_state_topic_matches_state_topic_helper():
    payload = discovery_payload("TH01", METRICS[0])

    assert payload["state_topic"] == state_topic("TH01")
    assert payload["state_topic"] == "govee/TH01/state"


def test_discovery_payload_availability_wired_to_status_topic():
    for metric in METRICS:
        payload = discovery_payload("TH01", metric)
        assert payload["availability_topic"] == STATUS_TOPIC
        assert payload["payload_available"] == "online"
        assert payload["payload_not_available"] == "offline"


def test_discovery_payload_expire_after_matches_module_constant():
    payload = discovery_payload("TH01", METRICS[0])

    assert payload["expire_after"] == EXPIRE_AFTER_SECONDS


def test_discovery_payload_has_entity_name_and_short_names():
    names = {metric.name for metric in METRICS}

    assert names == {"Temperature", "Humidity", "Battery", "Signal Strength"}
    for metric in METRICS:
        payload = discovery_payload("TH01", metric)
        assert payload["has_entity_name"] is True
        assert payload["name"] == metric.name


def test_battery_metric_device_class():
    battery = next(m for m in METRICS if m.object_id_suffix == "battery")
    assert battery.device_class == "battery"
    assert battery.unit == "%"


def test_rssi_metric_device_class():
    rssi = next(m for m in METRICS if m.object_id_suffix == "rssi")
    assert rssi.device_class == "signal_strength"
    assert rssi.unit == "dBm"
