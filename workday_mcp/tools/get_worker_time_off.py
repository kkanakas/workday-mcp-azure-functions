from __future__ import annotations

from workday_mcp.auth.identity_context import get_current_identity


def get_worker_time_off(client) -> list[dict]:
    identity = get_current_identity()
    worker = client.get_worker(identity.upn)
    entries = client.get_worker_time_off(worker.worker_id)
    return [{"date": e.date, "hours": e.hours, "type": e.type} for e in entries]
