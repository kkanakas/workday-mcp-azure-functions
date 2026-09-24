# workday_mcp/workday/models.py
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Worker:
    worker_id: str
    display_name: str
    email: str
    job_title: str = ""
    organization: str = ""


@dataclass(frozen=True)
class TimeOffEntry:
    date: str
    hours: float
    type: str


@dataclass(frozen=True)
class OrganizationInfo:
    organization_id: str
    name: str
    manager_worker_id: str = ""
    member_worker_ids: list[str] = field(default_factory=list)
