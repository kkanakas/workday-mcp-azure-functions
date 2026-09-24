import pytest

from workday_mcp.auth.identity_context import RequestIdentity, reset_current_identity, set_current_identity
from workday_mcp.tools.get_organization import get_organization
from workday_mcp.tools.get_worker import get_worker
from workday_mcp.tools.get_worker_time_off import get_worker_time_off
from workday_mcp.tools.search_workers import search_workers
from workday_mcp.workday.models import OrganizationInfo, TimeOffEntry, Worker


class FakeWorkdayClient:
    def __init__(self):
        self.worker = Worker(worker_id="w-1", display_name="Alice", email="alice@example.com", job_title="Engineer", organization="Eng")
        self.time_off = [TimeOffEntry(date="2026-01-05", hours=8, type="Vacation")]
        self.org = OrganizationInfo(organization_id="org-1", name="Engineering", manager_worker_id="w-9", member_worker_ids=["w-1"])
        self.search_results = [self.worker]
        self.last_worker_id_lookup = None

    def get_worker(self, upn):
        assert upn == "alice@example.com"
        return self.worker

    def get_worker_time_off(self, worker_id):
        self.last_worker_id_lookup = worker_id
        return self.time_off

    def get_organization(self, worker_id):
        self.last_worker_id_lookup = worker_id
        return self.org

    def search_workers(self, query, limit=20):
        assert query == "ali"
        return self.search_results


@pytest.fixture
def identity_ctx():
    identity = RequestIdentity(upn="alice@example.com", display_name="Alice", object_id="obj-1")
    token = set_current_identity(identity)
    yield identity
    reset_current_identity(token)


def test_get_worker_returns_caller_profile(identity_ctx):
    client = FakeWorkdayClient()
    result = get_worker(client)
    assert result["worker_id"] == "w-1"
    assert result["email"] == "alice@example.com"


def test_get_worker_time_off_scopes_to_caller(identity_ctx):
    client = FakeWorkdayClient()
    result = get_worker_time_off(client)
    assert result == [{"date": "2026-01-05", "hours": 8, "type": "Vacation"}]
    assert client.last_worker_id_lookup == "w-1"


def test_get_organization_scopes_to_caller(identity_ctx):
    client = FakeWorkdayClient()
    result = get_organization(client)
    assert result["name"] == "Engineering"
    assert client.last_worker_id_lookup == "w-1"


def test_search_workers_returns_list(identity_ctx):
    client = FakeWorkdayClient()
    result = search_workers(client, "ali")
    assert result[0]["worker_id"] == "w-1"
