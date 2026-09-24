# workday_mcp/workday/client.py
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from .models import OrganizationInfo, TimeOffEntry, Worker


class WorkdayApiError(Exception):
    pass


@dataclass
class _CachedToken:
    access_token: str
    expires_at: float


class WorkdayClient:
    def __init__(
        self,
        tenant_base_url: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        http_client: httpx.Client | None = None,
        clock=time.time,
    ):
        self._tenant_base_url = tenant_base_url.rstrip("/")
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._http_client = http_client or httpx.Client(timeout=15.0)
        self._clock = clock
        self._cached_token: _CachedToken | None = None

    def _get_access_token(self) -> str:
        if self._cached_token and self._cached_token.expires_at > self._clock() + 30:
            return self._cached_token.access_token

        response = self._http_client.post(
            self._token_url,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        if response.status_code != 200:
            raise WorkdayApiError(f"Workday token request failed: {response.status_code} {response.text}")

        payload = response.json()
        access_token = payload["access_token"]
        expires_in = payload.get("expires_in", 3600)
        self._cached_token = _CachedToken(access_token=access_token, expires_at=self._clock() + expires_in)
        return access_token

    def _get(self, path: str, params: dict | None = None) -> dict:
        token = self._get_access_token()
        response = self._http_client.get(
            f"{self._tenant_base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code != 200:
            raise WorkdayApiError(f"Workday API call failed: {response.status_code} {response.text}")
        return response.json()

    def get_worker(self, upn: str) -> Worker:
        data = self._get("/workers", params={"search": upn})
        entries = data.get("data", [])
        if not entries:
            raise WorkdayApiError(f"No worker found for {upn}")
        entry = entries[0]
        return Worker(
            worker_id=entry["id"],
            display_name=entry.get("descriptor", ""),
            email=upn,
            job_title=entry.get("jobTitle", ""),
            organization=entry.get("organization", ""),
        )

    def search_workers(self, query: str, limit: int = 20) -> list[Worker]:
        data = self._get("/workers", params={"search": query, "limit": limit})
        return [
            Worker(
                worker_id=entry["id"],
                display_name=entry.get("descriptor", ""),
                email=entry.get("email", ""),
                job_title=entry.get("jobTitle", ""),
                organization=entry.get("organization", ""),
            )
            for entry in data.get("data", [])
        ]

    def get_worker_time_off(self, worker_id: str) -> list[TimeOffEntry]:
        data = self._get(f"/workers/{worker_id}/timeOffEntries")
        return [
            TimeOffEntry(date=entry["date"], hours=entry["hours"], type=entry.get("type", ""))
            for entry in data.get("data", [])
        ]

    def get_organization(self, worker_id: str) -> OrganizationInfo:
        data = self._get(f"/workers/{worker_id}/organization")
        return OrganizationInfo(
            organization_id=data["id"],
            name=data.get("name", ""),
            manager_worker_id=data.get("managerId", ""),
            member_worker_ids=data.get("memberIds", []),
        )
