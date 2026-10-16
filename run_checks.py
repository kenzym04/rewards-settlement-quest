"""One-command evidence run: python run_checks.py

1. legacy implementation (in-memory ledger)  -> suite MUST fail (reproduces the defect)
2. fixed implementation, in-memory ledger     -> suite MUST pass
3. fixed implementation, SQLite ledger        -> suite MUST pass (real UNIQUE constraints)
4. legacy implementation, SQLite ledger       -> suite MUST still fail (the constraint stops the
                                                 double payout but not the false notifications)
5. mutants of the fixed code                  -> suite MUST fail for each (proves the checks have teeth)

Exit code 0 only when all expectations hold.
"""

import io
import os
import sys
import unittest
from datetime import timedelta
from typing import Callable, Dict, List, Tuple
from unittest import mock

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from rewards import settlement  # noqa: E402
from rewards import window as window_module  # noqa: E402
from rewards.notifier import NotificationError  # noqa: E402
from rewards.window import UTC  # noqa: E402


def run_suite() -> Tuple[int, List[str]]:
    """Run the whole suite quietly. Returns (tests_run, sorted failing test names)."""
    suite = unittest.defaultTestLoader.discover(
        os.path.join(ROOT, "tests"), top_level_dir=ROOT
    )
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    failing = [test.id().split(".")[-1] for test, _ in result.failures + result.errors]
    return result.testsRun, sorted(failing)


def with_impl(name: str, store: str = "memory") -> Tuple[int, List[str]]:
    os.environ["REWARDS_IMPL"] = name
    os.environ["REWARDS_STORE"] = store
    try:
        return run_suite()
    finally:
        del os.environ["REWARDS_IMPL"]
        del os.environ["REWARDS_STORE"]


# ---- mutants of the fixed implementation (each is a plausible regression) -------------------

def _inclusive_upper_boundary(moment, window):
    return window.start <= window_module.to_utc(moment) <= window.end


def _exclusive_lower_boundary(moment, window):
    return window.start < window_module.to_utc(moment) < window.end


def _ignore_utc_offset(moment):
    return moment.replace(tzinfo=UTC)


def _attempt_scoped_key(task_id):
    _attempt_scoped_key.counter += 1
    return "attempt-%d:%s" % (_attempt_scoped_key.counter, task_id)


_attempt_scoped_key.counter = 0


def _rollback_on_notification_failure(window, store, notifier):
    sent, failed = [], []
    for payout in store.unnotified_payouts(window.start):
        try:
            notifier.send(payout)
        except NotificationError:
            store._payouts.pop(payout.key)  # the forbidden behaviour: reverse the payout
            failed.append(payout.task_id)
            continue
        store.mark_notified(payout.key)
        sent.append(payout.task_id)
    return sent, failed


def _no_dedupe(tasks):
    return sorted(tasks, key=lambda t: (window_module.to_utc(t.completed_at), t.task_id))


# The ledger table without PRIMARY KEY / UNIQUE: what a missing migration would look like.
_SCHEMA_WITHOUT_CONSTRAINTS = """
CREATE TABLE IF NOT EXISTS payouts (
    key TEXT, task_id TEXT NOT NULL, account_id TEXT NOT NULL,
    credits INTEGER NOT NULL, window_start TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0
)
"""

# name -> (patch target, expectation, replacement, ledger kind used to run the suite)
MUTANTS: Dict[str, Tuple[str, str, object, str]] = {
    "upper boundary included": (
        "rewards.settlement.in_window", "kill", _inclusive_upper_boundary, "memory"),
    "lower boundary excluded": (
        "rewards.settlement.in_window", "kill", _exclusive_lower_boundary, "memory"),
    "UTC offset ignored": ("rewards.window.to_utc", "kill", _ignore_utc_offset, "memory"),
    "attempt-scoped payout key": (
        "rewards.settlement.payout_key", "kill", _attempt_scoped_key, "memory"),
    "payout reversed on notify failure": (
        "rewards.settlement.notify_pending", "kill", _rollback_on_notification_failure, "memory"),
    "DB UNIQUE constraints dropped": (
        "rewards.sqlite_store.SCHEMA", "kill", _SCHEMA_WITHOUT_CONSTRAINTS, "sqlite"),
    "input de-duplication removed": (
        "rewards.settlement.dedupe_tasks", "survive", _no_dedupe, "memory"),
}


def run_mutants() -> List[Tuple[str, str, bool, int]]:
    rows = []
    for name, (target, expectation, replacement, store_kind) in MUTANTS.items():
        _attempt_scoped_key.counter = 0
        with mock.patch(target, replacement):
            _, failing = with_impl("fixed", store_kind)
        killed = len(failing) > 0
        rows.append((name, expectation, killed, len(failing)))
    return rows


def report_stage(title: str, impl: str, store: str, must_fail: bool) -> bool:
    """Run the suite once, print the outcome, return True when it matches the expectation."""
    print(title)
    ran, failing = with_impl(impl, store)
    print("tests run: %d, failing: %d" % (ran, len(failing)))
    for name in failing:
        print("  FAIL %s" % name)
    return (len(failing) > 0) == must_fail


def main() -> int:
    ok = report_stage(
        "== 1. LEGACY (faulty) implementation, in-memory ledger: the suite must FAIL ==",
        "legacy", "memory", True)
    ok = report_stage(
        "\n== 2. FIXED implementation, in-memory ledger: the suite must PASS ==",
        "fixed", "memory", False) and ok
    ok = report_stage(
        "\n== 3. FIXED implementation, SQLite ledger (real UNIQUE constraints): must PASS ==",
        "fixed", "sqlite", False) and ok
    ok = report_stage(
        "\n== 4. LEGACY implementation, SQLite ledger: must still FAIL "
        "(constraint stops the double payout, not the false notifications) ==",
        "legacy", "sqlite", True) and ok

    print("\n== 5. MUTANTS of the fixed code ==")
    for name, expectation, killed, count in run_mutants():
        outcome = "KILLED (%d failing)" % count if killed else "SURVIVED"
        verdict = "as expected" if killed == (expectation == "kill") else "UNEXPECTED"
        print("  %-36s %-18s %s" % (name, outcome, verdict))
        ok = ok and verdict == "as expected"

    print("\nRESULT: %s" % ("ALL EXPECTATIONS HOLD" if ok else "EXPECTATIONS VIOLATED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
