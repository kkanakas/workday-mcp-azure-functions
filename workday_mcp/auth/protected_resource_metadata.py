from __future__ import annotations


def build_protected_resource_metadata(resource_url: str, tenant_id: str, scope: str) -> dict:
    return {
        "resource": resource_url,
        "authorization_servers": [f"https://login.microsoftonline.com/{tenant_id}/v2.0"],
        "scopes_supported": [scope],
        "bearer_methods_supported": ["header"],
    }
