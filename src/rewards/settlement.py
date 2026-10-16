"""Corrected (reference) settlement. Payout identity is the business key: the task ID.

Flow: window -> select eligible tasks -> pay (idempotent) -> notify (isolated).
"""

from typing import Dict, Iterable, List, Tuple

from rewards.models import (
    COMPLETED,
    REASON_ACCOUNT_BLOCKED,
    REASON_NOT_COMPLETED,
    Payout,
    SettlementConfig,
    SettlementReport,
    Task,
)
from rewards.notifier import NotificationError, Notifier
from rewards.store import Store
from rewards.window import Window, in_window, to_utc, window_for


def payout_key(task_id: str) -> str:
    """One payout per task ID, for all time. Must NOT include run or attempt identifiers."""
    return "task:%s" % task_id


def dedupe_tasks(tasks: Iterable[Task]) -> List[Task]:
    """Keep one row per task ID. For conflicting rows the earliest completed_at wins."""
    ordered = sorted(tasks, key=lambda t: (to_utc(t.completed_at), t.task_id))
    seen = set()
    unique: List[Task] = []
    for task in ordered:
        if task.task_id in seen:
            continue
        seen.add(task.task_id)
        unique.append(task)
    return unique


def select_eligible(
    tasks: Iterable[Task], window: Window, config: SettlementConfig
) -> Tuple[List[Task], Dict[str, Tuple[str, ...]]]:
    """Validate and filter tasks. Raises ValueError before any money moves."""
    eligible: List[Task] = []
    not_completed: List[str] = []
    blocked: List[str] = []
    for task in dedupe_tasks(tasks):
        if not in_window(task.completed_at, window):
            continue
        if task.status != COMPLETED:
            not_completed.append(task.task_id)
        elif task.account_id in config.blocked_accounts:
            blocked.append(task.task_id)
        else:
            eligible.append(task)
    skipped = {
        REASON_NOT_COMPLETED: tuple(not_completed),
        REASON_ACCOUNT_BLOCKED: tuple(blocked),
    }
    return eligible, skipped


def pay_tasks(
    eligible: Iterable[Task], window: Window, store: Store, config: SettlementConfig
) -> List[Payout]:
    """Create payouts that do not exist yet. Existing payouts are never modified."""
    created: List[Payout] = []
    for task in eligible:
        payout = Payout(
            key=payout_key(task.task_id),
            account_id=task.account_id,
            task_id=task.task_id,
            credits=config.credits_per_task,
            window_start=window.start,
        )
        if store.add_payout(payout):
            created.append(payout)
    return created


def notify_pending(
    window: Window, store: Store, notifier: Notifier
) -> Tuple[List[str], List[str]]:
    """Notify stored payouts not yet notified. A failure never touches the payout."""
    sent: List[str] = []
    failed: List[str] = []
    for payout in store.unnotified_payouts(window.start):
        try:
            notifier.send(payout)
        except NotificationError:
            failed.append(payout.task_id)
            continue
        store.mark_notified(payout.key)
        sent.append(payout.task_id)
    return sent, failed


def settle(
    run_at,
    tasks: Iterable[Task],
    store: Store,
    notifier: Notifier,
    config: SettlementConfig = SettlementConfig(),
) -> SettlementReport:
    """Run (or safely re-run) the settlement for the window containing run_at."""
    if config.credits_per_task <= 0:
        raise ValueError("credits_per_task must be positive")
    window = window_for(run_at)
    eligible, skipped = select_eligible(tasks, window, config)
    created = pay_tasks(eligible, window, store, config)
    sent, failed = notify_pending(window, store, notifier)
    return SettlementReport(
        window_start=window.start,
        window_end=window.end,
        new_payouts=tuple(created),
        skipped=skipped,
        notifications_sent=tuple(sent),
        notifications_failed=tuple(failed),
    )
