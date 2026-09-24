from __future__ import annotations

from workday_mcp.auth.identity_context import get_current_identity
from workday_mcp.workday.models import Worker


def _worker_to_dict(worker: Worker) -> dict:
    return {
        "worker_id": worker.worker_id,
        "display_name": worker.display_name,
        "email": worker.email,
        "job_title": worker.job_title,
        "organization": worker.organization,
    }


def get_worker(client) -> dict:
    identity = get_current_identity()
    worker = client.get_worker(identity.upn)
    return _worker_to_dict(worker)
