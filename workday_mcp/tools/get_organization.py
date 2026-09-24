from __future__ import annotations

from workday_mcp.auth.identity_context import get_current_identity


def get_organization(client) -> dict:
    identity = get_current_identity()
    worker = client.get_worker(identity.upn)
    org = client.get_organization(worker.worker_id)
    return {
        "organization_id": org.organization_id,
        "name": org.name,
        "manager_worker_id": org.manager_worker_id,
        "member_worker_ids": org.member_worker_ids,
    }
