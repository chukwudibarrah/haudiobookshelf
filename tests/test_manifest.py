"""Checks that the packaging metadata stays consistent with the code.

These are the mistakes that only show up after a release: a service described
in one place and registered in another, a translation key that no entity uses,
a manifest hassfest will reject.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

COMPONENT = Path(__file__).parent.parent / "custom_components" / "audiobookshelf"

REQUIRED_MANIFEST_KEYS = {
    "domain",
    "name",
    "codeowners",
    "config_flow",
    "documentation",
    "integration_type",
    "iot_class",
    "issue_tracker",
    "requirements",
    "version",
}


def _load(name: str):
    return json.loads((COMPONENT / name).read_text())


def test_manifest_is_hassfest_shaped() -> None:
    """hassfest requires specific keys, and domain/name before the rest sorted."""
    manifest = _load("manifest.json")
    assert set(manifest) >= REQUIRED_MANIFEST_KEYS

    keys = list(manifest)
    assert keys[0] == "domain"
    assert keys[1] == "name"
    assert keys[2:] == sorted(keys[2:])

    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["documentation"].startswith("https://")
    assert manifest["issue_tracker"].startswith("https://")
    assert all(owner.startswith("@") for owner in manifest["codeowners"])
    assert manifest["domain"] == COMPONENT.name


def test_hacs_manifest() -> None:
    """HACS needs a name and a minimum Home Assistant version."""
    hacs = json.loads((COMPONENT.parent.parent / "hacs.json").read_text())
    assert hacs["name"]
    assert re.fullmatch(r"\d{4}\.\d+\.\d+", hacs["homeassistant"])


def test_translations_match_strings() -> None:
    """translations/en.json is the shipped copy of strings.json."""
    assert _load("strings.json") == _load("translations/en.json")


def test_services_are_described_and_registered() -> None:
    """Every service exists in services.yaml, strings.json and the code."""
    from custom_components.audiobookshelf import (
        SERVICE_MARK_FINISHED,
        SERVICE_MARK_UNFINISHED,
        SERVICE_REFRESH,
        SERVICE_SET_PROGRESS,
    )

    registered = {
        SERVICE_MARK_FINISHED,
        SERVICE_MARK_UNFINISHED,
        SERVICE_SET_PROGRESS,
        SERVICE_REFRESH,
    }
    described = set(yaml.safe_load((COMPONENT / "services.yaml").read_text()))
    translated = set(_load("strings.json")["services"])

    assert described == registered
    assert translated == registered


def test_service_fields_are_described() -> None:
    """Each service's fields appear in both services.yaml and strings.json."""
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    strings = _load("strings.json")["services"]

    for name, service in services.items():
        yaml_fields = set(service.get("fields") or {})
        string_fields = set(strings[name].get("fields") or {})
        assert yaml_fields == string_fields, f"{name} fields differ"


def test_entity_translation_keys_exist() -> None:
    """Every translation key an entity declares is present in strings.json."""
    from custom_components.audiobookshelf.image import IMAGES
    from custom_components.audiobookshelf.sensor import SENSORS

    entity_strings = _load("strings.json")["entity"]

    for description in SENSORS:
        assert description.translation_key in entity_strings["sensor"], (
            f"sensor {description.key} has no name in strings.json"
        )
    for key, _source in IMAGES:
        assert key in entity_strings["image"]
    assert "listening" in entity_strings["binary_sensor"]


def test_config_flow_error_keys_are_translated() -> None:
    """Every error the config flow can raise has a message."""
    from custom_components.audiobookshelf import config_flow

    source = Path(config_flow.__file__).read_text()
    raised = set(re.findall(r'return None, "(\w+)"', source))
    raised.add("invalid_url")
    translated = set(_load("strings.json")["config"]["error"])
    assert translated >= raised


def test_card_is_bundled() -> None:
    """The integration cannot serve a card it does not ship."""
    from custom_components.audiobookshelf.const import CARD_FILENAME

    card = COMPONENT / "frontend" / CARD_FILENAME
    assert card.is_file()
    body = card.read_text()
    assert 'customElements.define("audiobookshelf-card"' in body
    # The card must never be given the Audiobookshelf token.
    assert "Bearer" not in body
