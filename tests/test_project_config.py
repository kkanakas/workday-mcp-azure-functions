# tests/test_project_config.py
"""Regression guards for config that only breaks against real Entra/deployments."""

from __future__ import annotations

import json
import re
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTER_SCRIPT = REPO_ROOT / "scripts" / "register-entra-apps.sh"


def _api_object_from_script() -> dict:
    """Parse the JSON passed to `az ad app update --set api=...`."""
    source = REGISTER_SCRIPT.read_text()
    match = re.search(r'--set api="(?P<json>\{.*?\n\})"', source, re.DOTALL)
    assert match, "could not find the --set api=... payload in register-entra-apps.sh"
    payload = match.group("json").replace('\\"', '"')
    payload = re.sub(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", "placeholder", payload)
    return json.loads(payload)


def test_entra_app_requests_v2_access_tokens():
    """I2: the server and the APIM policy both validate the v2 issuer, so the
    app registration must ask Entra for v2 tokens."""
    api = _api_object_from_script()
    assert api["requestedAccessTokenVersion"] == 2


def test_server_and_apim_agree_on_the_v2_issuer():
    validator_source = (REPO_ROOT / "workday_mcp" / "auth" / "jwt_validator.py").read_text()
    apim_source = (REPO_ROOT / "infra" / "modules" / "apim.bicep").read_text()
    assert 'https://login.microsoftonline.com/{tenant_id}/v2.0"' in validator_source
    assert "https://login.microsoftonline.com/{0}/v2.0</issuer>" in apim_source


def test_exposed_scope_is_still_access_as_user():
    api = _api_object_from_script()
    assert [scope["value"] for scope in api["oauth2PermissionScopes"]] == ["access_as_user"]


def test_mcp_dependency_is_pinned_to_the_installed_version():
    """I6: the 1.x -> 2.x rename already broke this project once."""
    requirements = (REPO_ROOT / "requirements.txt").read_text()
    match = re.search(r"^mcp==(?P<version>[0-9][^\s#]*)", requirements, re.MULTILINE)
    assert match, f"mcp must be pinned with ==, got:\n{requirements}"
    assert match.group("version") == metadata.version("mcp")


def test_local_settings_example_audience_matches_the_client_id():
    """I3: with v2 tokens the audience is the client ID GUID, not an api:// URI."""
    values = json.loads((REPO_ROOT / "local.settings.json.example").read_text())["Values"]
    assert values["ENTRA_API_AUDIENCE"] == values["ENTRA_CLIENT_ID"]
    assert not values["ENTRA_API_AUDIENCE"].startswith("api://")
