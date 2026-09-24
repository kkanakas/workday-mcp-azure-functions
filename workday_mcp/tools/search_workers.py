from __future__ import annotations


def search_workers(client, query: str, limit: int = 20) -> list[dict]:
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
