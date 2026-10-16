"""Plain data types shared by the settlement implementations."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, FrozenSet, Tuple

COMPLETED = "completed"

REASON_NOT_COMPLETED = "not_completed"
REASON_ACCOUNT_BLOCKED = "account_blocked"

DEFAULT_CREDITS_PER_TASK = 10


@dataclass(frozen=True)
class Task:
    task_id: str
    account_id: str
    completed_at: datetime
    status: str = COMPLETED


@dataclass(frozen=True)
class Payout:
    key: str
    account_id: str
    task_id: str
    credits: int
    window_start: datetime


@dataclass(frozen=True)
class SettlementConfig:
    """Admin settings. Assumption: snapshot taken at the start of each run."""

    credits_per_task: int = DEFAULT_CREDITS_PER_TASK
    blocked_accounts: FrozenSet[str] = frozenset()


@dataclass(frozen=True)
class SettlementReport:
    window_start: datetime
    window_end: datetime
    new_payouts: Tuple[Payout, ...]
    skipped: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    notifications_sent: Tuple[str, ...] = ()
    notifications_failed: Tuple[str, ...] = ()
