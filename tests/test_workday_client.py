# tests/test_workday_client.py
import httpx
import pytest

from workday_mcp.workday.client import WorkdayApiError, WorkdayClient


def make_client(handler, clock=lambda: 1_000_000.0):
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    return WorkdayClient(
        tenant_base_url="https://wd.example.com/api/v1/acme",
        token_url="https://wd.example.com/oauth2/token",
        client_id="isu-client",
        client_secret="isu-secret",
        http_client=http_client,
        clock=clock,
    )


def test_get_worker_returns_worker_and_caches_token():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        assert request.headers["Authorization"] == "Bearer tok-1"
        return httpx.Response(200, json={"data": [{"id": "w-1", "descriptor": "Alice Smith", "jobTitle": "Engineer"}]})

    client = make_client(handler)
    worker = client.get_worker("alice@example.com")
    worker2 = client.get_worker("alice@example.com")

    assert worker.worker_id == "w-1"
    assert worker.display_name == "Alice Smith"
    assert worker.email == "alice@example.com"
    assert worker2.worker_id == "w-1"
    assert calls.count("/oauth2/token") == 1


def test_token_refreshed_after_expiry():
    time_box = {"now": 1_000_000.0}
    token_calls = {"count": 0}

    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            token_calls["count"] += 1
            return httpx.Response(200, json={"access_token": f"tok-{token_calls['count']}", "expires_in": 60})
        return httpx.Response(200, json={"data": [{"id": "w-1", "descriptor": "Alice"}]})

    client = make_client(handler, clock=lambda: time_box["now"])
    client.get_worker("alice@example.com")
    time_box["now"] += 120
    client.get_worker("alice@example.com")

    assert token_calls["count"] == 2


def test_get_worker_raises_when_not_found():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"data": []})

    client = make_client(handler)
    with pytest.raises(WorkdayApiError, match="No worker found"):
        client.get_worker("nobody@example.com")


def test_search_workers_returns_list():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"data": [
            {"id": "w-1", "descriptor": "Alice", "email": "alice@example.com"},
            {"id": "w-2", "descriptor": "Bob", "email": "bob@example.com"},
        ]})

    client = make_client(handler)
    workers = client.search_workers("a")

    assert [w.worker_id for w in workers] == ["w-1", "w-2"]


def test_get_worker_time_off_returns_entries():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"data": [{"date": "2026-01-05", "hours": 8, "type": "Vacation"}]})

    client = make_client(handler)
    entries = client.get_worker_time_off("w-1")

    assert entries[0].type == "Vacation"
    assert entries[0].hours == 8


def test_get_organization_returns_info():
    def handler(request):
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
        return httpx.Response(200, json={"id": "org-1", "name": "Engineering", "managerId": "w-9", "memberIds": ["w-1", "w-2"]})

    client = make_client(handler)
    org = client.get_organization("w-1")

    assert org.name == "Engineering"
    assert org.member_worker_ids == ["w-1", "w-2"]


def test_token_request_failure_raises():
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    client = make_client(handler)
    with pytest.raises(WorkdayApiError, match="401"):
        client.get_worker("alice@example.com")
