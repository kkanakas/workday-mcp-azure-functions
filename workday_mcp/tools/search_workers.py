from __future__ import annotations

from workday_mcp.auth.identity_context import get_current_identity

MAX_SEARCH_LIMIT = 100
"""Upper bound on the caller-supplied result count, so a caller cannot ask for
an unbounded slice of the worker directory."""


def search_workers(client, query: str, limit: int = 20) -> list[dict]:
    # The directory search is not scoped to the caller, but the tool must still
    # only run inside an authenticated request context: if the middleware failed
    # to resolve an identity, NoIdentityError propagates and this fails closed.
    get_current_identity()

    limit = min(limit, MAX_SEARCH_LIMIT)

    workers = client.search_workers(query, limit=limit)
    return [
        {
            "worker_id": w.worker_id,
            "display_name": w.display_name,
            "email": w.email,
            "job_title": w.job_title,
            "organization": w.organization,
        }
        for w in workers
    ]
