"""Tests for the config-flow field labels.

Home Assistant reads a custom integration's labels from
`translations/en.json`; `strings.json` is the core-development convention
this fork inherited and still carries. They must stay identical (there's no
build step here that generates one from the other), and the tier fields'
internal keys still say "gallons" for backward compatibility with stored
config entries -- so their *visible* labels must not repeat that, since
the tier math actually runs in whatever Unit Type is chosen (CCF for SLC).

Pure JSON checks -- no `homeassistant` import needed.
"""

from __future__ import annotations

import json
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
TIER_GALLON_KEYS = ("tier1_gallons", "tier2_gallons")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_strings_json_and_translations_en_json_are_identical():
    assert _load(PKG / "strings.json") == _load(PKG / "translations" / "en.json")


def test_tier_size_labels_do_not_claim_gallons():
    translations = _load(PKG / "translations" / "en.json")
    for section in (translations["config"]["step"]["user"], translations["options"]["step"]["init"]):
        for key in TIER_GALLON_KEYS:
            assert "gallon" not in section["data"][key].lower()


def test_every_tier_field_has_a_description_in_both_forms():
    translations = _load(PKG / "translations" / "en.json")
    for section in (translations["config"]["step"]["user"], translations["options"]["step"]["init"]):
        for key in (*TIER_GALLON_KEYS, "tier1_price", "tier2_price", "tier3_price", "service_fee", "unit_type"):
            assert section["data_description"][key]
