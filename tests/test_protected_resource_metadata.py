from workday_mcp.auth.protected_resource_metadata import build_protected_resource_metadata


def test_build_protected_resource_metadata():
    metadata = build_protected_resource_metadata(
        resource_url="https://workday-mcp.example.com/mcp",
        tenant_id="tenant-abc",
        scope="api://workday-mcp/access_as_user",
    )

    assert metadata["resource"] == "https://workday-mcp.example.com/mcp"
    assert metadata["authorization_servers"] == ["https://login.microsoftonline.com/tenant-abc/v2.0"]
    assert metadata["scopes_supported"] == ["api://workday-mcp/access_as_user"]
    assert metadata["bearer_methods_supported"] == ["header"]
