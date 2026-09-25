# tests/test_infra_bicep.py
"""Static checks on the Bicep templates that catch deploy-time-only failures.

These would have caught two real bugs: an APIM policy whose XML did not parse
(unescaped `"` inside an XML attribute) and generated Storage/Key Vault names
that exceeded Azure's 24-character limits.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

INFRA = Path(__file__).resolve().parent.parent / "infra"
MAIN_BICEP = INFRA / "main.bicep"
APIM_BICEP = INFRA / "modules" / "apim.bicep"

# Azure's documented limits.
MAX_STORAGE_ACCOUNT_NAME = 24
MAX_KEY_VAULT_NAME = 24

# uniqueString() returns 13 characters today; assume a longer one so the
# generated names keep headroom if that ever changes.
UNIQUE_STRING_LENGTHS = (13, 16)


def _extract_policy_xml(source: str) -> str:
    """Pull the XML out of `value: format('''<policies>...''', a, b, c)`."""
    match = re.search(r"format\('''(?P<xml>.*?)''',(?P<args>[^)]*)\)", source, re.DOTALL)
    assert match, "could not locate the format('''...''') policy expression in apim.bicep"
    xml = match.group("xml")
    # Substitute the format() placeholders with plausible deployed values.
    substitutions = [
        "11111111-2222-3333-4444-555555555555",  # {0} tenant id
        "66666666-7777-8888-9999-000000000000",  # {1} audience
        "fake-function-host-key",  # {2} function key
    ]
    for index, value in enumerate(substitutions):
        xml = xml.replace("{%d}" % index, value)
    assert not re.search(r"\{\d+\}", xml), "unsubstituted format placeholder left in policy XML"
    return xml


def test_apim_policy_is_well_formed_xml():
    xml = _extract_policy_xml(APIM_BICEP.read_text())
    # Raises xml.etree.ElementTree.ParseError if the policy is malformed, which
    # is exactly how APIM would reject it at deploy time.
    root = ET.fromstring(xml)
    assert root.tag == "policies"


def test_apim_policy_well_known_bypass_condition_survives_xml_parsing():
    """The bypass condition must still name the well-known path after escaping."""
    root = ET.fromstring(_extract_policy_xml(APIM_BICEP.read_text()))
    conditions = [when.get("condition") for when in root.iter("when")]
    assert conditions, "no <when> branch found in the policy"
    assert any(
        '"/.well-known/oauth-protected-resource"' in (condition or "") for condition in conditions
    ), f"well-known bypass condition lost its quoted path after parsing: {conditions}"


def _render_name_var(source: str, var_name: str, unique_string_length: int) -> str:
    """Resolve `var <var_name> = ...` to the literal name it deploys as."""
    match = re.search(rf"^var {var_name} = (?P<expr>.*)$", source, re.MULTILINE)
    assert match, f"could not find `var {var_name}` in main.bicep"
    expr = match.group("expr")

    literals = re.findall(r"'([^']*)'", expr)
    assert literals, f"{var_name} expression has no string literal to evaluate: {expr}"
    name = literals[0]

    base_name_match = re.search(r"^param baseName string = '([^']*)'", source, re.MULTILINE)
    assert base_name_match, "could not find the baseName param default"
    name = name.replace("${baseName}", base_name_match.group(1))
    name = name.replace("${uniqueString(resourceGroup().id)}", "u" * unique_string_length)

    assert "${" not in name, f"unresolved interpolation in {var_name}: {name}"
    if "replace(" in expr:
        assert len(literals) >= 3, f"cannot evaluate replace() in {var_name}: {expr}"
        name = name.replace(literals[1], literals[2])
    if "toLower(" in expr:
        name = name.lower()
    return name


@pytest.mark.parametrize("unique_string_length", UNIQUE_STRING_LENGTHS)
def test_storage_account_name_fits_azure_limits(unique_string_length):
    name = _render_name_var(MAIN_BICEP.read_text(), "storageAccountName", unique_string_length)
    assert len(name) <= MAX_STORAGE_ACCOUNT_NAME, f"storage account name {name!r} is {len(name)} chars"
    assert re.fullmatch(r"[a-z0-9]{3,24}", name), f"storage account name {name!r} is not lowercase alphanumeric"


@pytest.mark.parametrize("unique_string_length", UNIQUE_STRING_LENGTHS)
def test_key_vault_name_fits_azure_limits(unique_string_length):
    name = _render_name_var(MAIN_BICEP.read_text(), "keyVaultName", unique_string_length)
    assert len(name) <= MAX_KEY_VAULT_NAME, f"key vault name {name!r} is {len(name)} chars"
    assert re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]{2,23}", name), f"key vault name {name!r} is not a legal vault name"


def test_module_name_params_declare_max_length():
    """A future regression should fail at `az bicep build`, not at deploy time."""
    for module, param in (("storage.bicep", "storageAccountName"), ("key-vault.bicep", "keyVaultName")):
        source = (INFRA / "modules" / module).read_text()
        match = re.search(rf"@maxLength\((?P<max>\d+)\)\s*\nparam {param} string", source)
        assert match, f"{module} does not constrain {param} with @maxLength"
        assert int(match.group("max")) <= 24


def test_function_app_client_id_setting_uses_its_own_param():
    """ENTRA_CLIENT_ID must come from entraClientId, not be aliased to the audience."""
    source = (INFRA / "modules" / "function-app.bicep").read_text()
    assert re.search(r"^param entraClientId string$", source, re.MULTILINE)
    assert "{ name: 'ENTRA_CLIENT_ID', value: entraClientId }" in source
    assert "{ name: 'ENTRA_API_AUDIENCE', value: entraApiAudience }" in source
    # main.bicep must thread the new param through to the module.
    assert "entraClientId: entraClientId" in MAIN_BICEP.read_text()
