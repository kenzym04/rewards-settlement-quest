"""FAULTY legacy settlement kept as a fixture to reproduce the defect (see docs/defect-report.md).

Defect: the payout key is built from the attempt number and the input row position, not from
the task ID. The ledger's uniqueness check therefore never fires, so every retry of the same
window, and every duplicated input row, creates another payout.
"""

import itertools
from typing import Iterable

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
from rewards.window import in_window, to_utc, window_for

_ATTEMPTS = itertools.count(1)


def settle(
    run_at,
    tasks: Iterable[Task],
    store: Store,
    notifier: Notifier,
    config: SettlementConfig = SettlementConfig(),
) -> SettlementReport:
    window = window_for(run_at)
    rows = list(tasks)
    for task in rows:
        to_utc(task.completed_at)  # validate up front, as the fixed version does
    attempt = next(_ATTEMPTS)
    created, sent, failed = [], [], []
    not_completed, blocked = [], []
    for row, task in enumerate(rows):
        if not in_window(task.completed_at, window):
            continue
        if task.status != COMPLETED:
            not_completed.append(task.task_id)
            continue
        if task.account_id in config.blocked_accounts:
            blocked.append(task.task_id)
            continue
        payout = Payout(
            key="attempt-%d-row-%d" % (attempt, row),  # <-- the defect
            account_id=task.account_id,
            task_id=task.task_id,
            credits=config.credits_per_task,
            window_start=window.start,
        )
        store.add_payout(payout)
        created.append(payout)
        try:
            notifier.send(payout)
        except NotificationError:
            failed.append(task.task_id)
            continue
        store.mark_notified(payout.key)
        sent.append(task.task_id)
    return SettlementReport(
        window_start=window.start,
        window_end=window.end,
        new_payouts=tuple(created),
        skipped={
            REASON_NOT_COMPLETED: tuple(not_completed),
            REASON_ACCOUNT_BLOCKED: tuple(blocked),
        },
        notifications_sent=tuple(sent),
        notifications_failed=tuple(failed),
    )
