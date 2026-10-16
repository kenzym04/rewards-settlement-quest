"""Business-rule regression suite. Run against REWARDS_IMPL=fixed (must pass) or legacy (must fail).

Window under test for RUN_AT (Tue 2026-10-13 09:00 UTC): [2026-10-05 00:00Z, 2026-10-12 00:00Z).
"""

import os
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone

from rewards.models import (
    REASON_ACCOUNT_BLOCKED,
    REASON_NOT_COMPLETED,
    Payout,
    SettlementConfig,
    Task,
)
from rewards.sqlite_store import SqliteStore
from tests.fakes import (
    CrashAfterSendStore,
    CrashingStore,
    RecordingNotifier,
    StoreCrash,
    load_impl,
    make_store,
)

CONCURRENT_RUNS = 6
CONCURRENT_TASKS = 20
THREAD_JOIN_SECONDS = 120

UTC = timezone.utc
RUN_AT = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
WINDOW_START = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
MID_WINDOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
NEXT_RUN_AT = RUN_AT + timedelta(days=7)


def task(task_id, completed_at=MID_WINDOW, account="acct-1", status="completed"):
    return Task(task_id=task_id, account_id=account, completed_at=completed_at, status=status)


class SettlementTestCase(unittest.TestCase):
    def setUp(self):
        self.impl = load_impl()
        self.directory = tempfile.mkdtemp(prefix="rewards-")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.store = self.new_store()
        self.notifier = RecordingNotifier(self.store)

    def new_store(self):
        """A fresh ledger of the kind chosen by REWARDS_STORE (memory by default)."""
        return make_store(self.directory)

    def settle(self, tasks, run_at=RUN_AT, config=SettlementConfig(), store=None, notifier=None):
        return self.impl.settle(
            run_at,
            tasks,
            store if store is not None else self.store,
            notifier if notifier is not None else self.notifier,
            config,
        )

    def paid_task_ids(self, store=None):
        return sorted(p.task_id for p in (store or self.store).payouts())


class TestHappyPathAndWindow(SettlementTestCase):
    def test_tc01_happy_path_pays_10_credits_per_task_and_notifies_after_payout(self):
        tasks = [task("t1"), task("t2"), task("t3", account="acct-2")]
        report = self.settle(tasks)
        self.assertEqual(self.paid_task_ids(), ["t1", "t2", "t3"])
        self.assertEqual(self.store.total_credits("acct-1"), 20)
        self.assertEqual(self.store.total_credits("acct-2"), 10)
        self.assertEqual(sorted(self.notifier.sent), ["t1", "t2", "t3"])
        self.assertEqual(self.notifier.sent_without_payout, [])
        self.assertEqual(report.window_start, WINDOW_START)
        self.assertEqual(report.window_end, WINDOW_END)

    def test_tc02_lower_boundary_is_included(self):
        before = WINDOW_START - timedelta(seconds=1)
        self.settle([task("at-start", WINDOW_START), task("just-before", before)])
        self.assertEqual(self.paid_task_ids(), ["at-start"])

    def test_tc03_upper_boundary_is_excluded_and_paid_next_week_once(self):
        last_second = WINDOW_END - timedelta(seconds=1)
        tasks = [task("last-second", last_second), task("at-end", WINDOW_END)]
        self.settle(tasks)
        self.assertEqual(self.paid_task_ids(), ["last-second"])
        self.settle(tasks, run_at=NEXT_RUN_AT)
        self.assertEqual(self.paid_task_ids(), ["at-end", "last-second"])

    def test_tc04_task_times_in_other_timezones_are_converted_to_utc(self):
        cases = [
            ("plus3-in", datetime(2026, 10, 12, 2, 59, tzinfo=timezone(timedelta(hours=3))), True),
            ("minus2-out", datetime(2026, 10, 11, 23, 30, tzinfo=timezone(timedelta(hours=-2))), False),
            ("plus3-start-in", datetime(2026, 10, 5, 3, 0, tzinfo=timezone(timedelta(hours=3))), True),
            ("plus3-start-out", datetime(2026, 10, 5, 2, 59, tzinfo=timezone(timedelta(hours=3))), False),
        ]
        self.settle([task(name, moment) for name, moment, _ in cases])
        expected = sorted(name for name, _, included in cases if included)
        self.assertEqual(self.paid_task_ids(), expected)

    def test_tc05_run_time_in_other_timezone_maps_to_same_window(self):
        run_at = datetime(2026, 10, 13, 12, 0, tzinfo=timezone(timedelta(hours=3)))
        report = self.settle([task("t1")], run_at=run_at)
        self.assertEqual((report.window_start, report.window_end), (WINDOW_START, WINDOW_END))
        self.assertEqual(self.paid_task_ids(), ["t1"])

    def test_tc06_naive_datetime_is_rejected_before_any_payout(self):
        naive = datetime(2026, 10, 8, 12, 0)
        with self.assertRaises(ValueError):
            self.settle([task("ok"), task("naive", naive)])
        self.assertEqual(self.paid_task_ids(), [])


class TestEligibility(SettlementTestCase):
    def test_tc07_non_completed_tasks_are_skipped_and_not_notified(self):
        report = self.settle([task("done"), task("open", status="in_progress")])
        self.assertEqual(self.paid_task_ids(), ["done"])
        self.assertEqual(self.notifier.sent, ["done"])
        self.assertEqual(report.skipped[REASON_NOT_COMPLETED], ("open",))

    def test_tc08_blocked_account_is_skipped_and_reported(self):
        config = SettlementConfig(blocked_accounts=frozenset({"acct-bad"}))
        report = self.settle([task("good"), task("bad", account="acct-bad")], config=config)
        self.assertEqual(self.paid_task_ids(), ["good"])
        self.assertEqual(report.skipped[REASON_ACCOUNT_BLOCKED], ("bad",))

    def test_tc09_empty_input_creates_nothing(self):
        report = self.settle([])
        self.assertEqual(self.paid_task_ids(), [])
        self.assertEqual(self.notifier.attempted, [])
        self.assertEqual(report.new_payouts, ())


class TestDuplicatesAndRetries(SettlementTestCase):
    """The selected failure family: a task must be paid exactly once."""

    def test_tc10_duplicate_task_id_in_input_is_paid_once(self):
        self.settle([task("dup"), task("dup"), task("other")])
        self.assertEqual(self.paid_task_ids(), ["dup", "other"])
        self.assertEqual(self.store.total_credits("acct-1"), 20)

    def test_tc11_conflicting_duplicate_uses_earliest_completed_at(self):
        late_copy = task("dup", WINDOW_END + timedelta(hours=5))
        self.settle([late_copy, task("dup", MID_WINDOW)])
        self.assertEqual(self.paid_task_ids(), ["dup"])

    def test_tc12_retry_with_same_input_creates_no_second_payout(self):
        tasks = [task("t1"), task("t2")]
        self.settle(tasks)
        retry_notifier = RecordingNotifier(self.store)
        retry_report = self.settle(tasks, notifier=retry_notifier)
        self.assertEqual(self.paid_task_ids(), ["t1", "t2"])
        self.assertEqual(self.store.total_credits("acct-1"), 20)
        self.assertEqual(retry_notifier.attempted, [])
        self.assertEqual(retry_report.new_payouts, ())

    def test_tc13_task_paid_in_earlier_window_is_not_paid_again_later(self):
        self.settle([task("t1")])
        reappeared = task("t1", completed_at=NEXT_RUN_AT - timedelta(days=3))
        self.settle([reappeared], run_at=NEXT_RUN_AT)
        self.assertEqual(self.paid_task_ids(), ["t1"])

    def test_tc14_retry_after_config_change_keeps_original_credits(self):
        self.settle([task("t1")])
        self.settle([task("t1")], config=SettlementConfig(credits_per_task=20))
        self.assertEqual(self.store.total_credits("acct-1"), 10)


class TestPartialFailure(SettlementTestCase):
    def test_tc15_crash_mid_run_then_retry_pays_each_task_exactly_once(self):
        store = CrashingStore(self.new_store(), crash_on_call=3)  # 2 payouts ok, 3rd call crashes
        notifier = RecordingNotifier(store)
        tasks = [task("t1"), task("t2"), task("t3"), task("t4")]
        with self.assertRaises(StoreCrash):
            self.settle(tasks, store=store, notifier=notifier)
        self.assertEqual(len(store.payouts()), 2)
        store.disarm()
        self.settle(tasks, store=store, notifier=notifier)
        self.assertEqual(self.paid_task_ids(store), ["t1", "t2", "t3", "t4"])
        self.assertEqual(store.total_credits("acct-1"), 40)
        self.assertEqual(sorted(notifier.sent), ["t1", "t2", "t3", "t4"])
        self.assertEqual(notifier.sent_without_payout, [])

    def test_tc16_notification_failure_does_not_reverse_payout(self):
        notifier = RecordingNotifier(self.store, failing_task_ids=["t2"])
        report = self.settle([task("t1"), task("t2"), task("t3")], notifier=notifier)
        self.assertEqual(self.paid_task_ids(), ["t1", "t2", "t3"])
        self.assertEqual(self.store.total_credits("acct-1"), 30)
        self.assertEqual(report.notifications_failed, ("t2",))
        self.assertEqual(sorted(notifier.sent), ["t1", "t3"])

    def test_tc17_retry_after_notification_failure_resends_only_the_failed_one(self):
        tasks = [task("t1"), task("t2"), task("t3")]
        failing = RecordingNotifier(self.store, failing_task_ids=["t2"])
        self.settle(tasks, notifier=failing)
        healthy = RecordingNotifier(self.store)
        self.settle(tasks, notifier=healthy)
        self.assertEqual(healthy.attempted, ["t2"])
        self.assertEqual(self.paid_task_ids(), ["t1", "t2", "t3"])
        self.assertEqual(self.store.total_credits("acct-1"), 30)

    def test_tc18_crash_between_send_and_mark_notified_never_double_pays(self):
        store = CrashAfterSendStore(self.new_store())
        tasks = [task("t1"), task("t2")]
        with self.assertRaises(StoreCrash):
            self.settle(tasks, store=store, notifier=RecordingNotifier(store))
        self.assertEqual(self.paid_task_ids(store), ["t1", "t2"])  # payouts are already stored
        store.disarm()
        retry_notifier = RecordingNotifier(store)
        self.settle(tasks, store=store, notifier=retry_notifier)
        self.assertEqual(self.paid_task_ids(store), ["t1", "t2"])
        self.assertEqual(store.total_credits("acct-1"), 20)
        # Documented at-least-once behaviour: t1 was sent before the crash and is sent again.
        self.assertEqual(retry_notifier.attempted, ["t1", "t2"])
        self.assertEqual(retry_notifier.sent_without_payout, [])


class TestAdminChanges(SettlementTestCase):
    def test_tc19_unblocked_account_is_paid_once_on_rerun_of_same_window(self):
        tasks = [task("good"), task("bad", account="acct-bad")]
        blocked = SettlementConfig(blocked_accounts=frozenset({"acct-bad"}))
        self.settle(tasks, config=blocked)
        self.assertEqual(self.paid_task_ids(), ["good"])
        self.settle(tasks, config=SettlementConfig())  # admin unblocked the account
        self.settle(tasks, config=SettlementConfig())  # and the job fires once more
        self.assertEqual(self.paid_task_ids(), ["bad", "good"])
        self.assertEqual(self.store.total_credits("acct-bad"), 10)
        self.assertEqual(self.store.total_credits("acct-1"), 10)


class TestLedgerAndConcurrency(unittest.TestCase):
    """Always runs against the SQLite ledger, whatever REWARDS_STORE says."""

    def setUp(self):
        self.impl = load_impl()
        self.directory = tempfile.mkdtemp(prefix="rewards-")
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.store = SqliteStore(os.path.join(self.directory, "ledger.db"))

    def run_concurrently(self, tasks, notifiers):
        """Start one settle() per notifier at the same moment. Returns the list of errors."""
        barrier = threading.Barrier(len(notifiers))
        errors = []

        def worker(notifier):
            try:
                barrier.wait(timeout=THREAD_JOIN_SECONDS)
                self.impl.settle(RUN_AT, tasks, self.store, notifier, SettlementConfig())
            except Exception as exc:  # collected and asserted by the caller
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in notifiers]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=THREAD_JOIN_SECONDS)
        return errors

    def test_tc20_concurrent_runs_for_one_window_pay_each_task_once(self):
        tasks = [task("c%02d" % i) for i in range(CONCURRENT_TASKS)]
        notifiers = [RecordingNotifier(self.store) for _ in range(CONCURRENT_RUNS)]
        errors = self.run_concurrently(tasks, notifiers)
        self.assertEqual(errors, [])
        expected_ids = sorted(t.task_id for t in tasks)
        self.assertEqual(sorted(p.task_id for p in self.store.payouts()), expected_ids)
        self.assertEqual(self.store.total_credits("acct-1"), 10 * CONCURRENT_TASKS)
        delivered = set()
        for notifier in notifiers:
            self.assertEqual(notifier.sent_without_payout, [])
            delivered.update(notifier.sent)
        self.assertEqual(sorted(delivered), expected_ids)  # at-least-once, never for unpaid

    def test_tc21_database_rejects_a_second_payout_for_the_same_task_id(self):
        first = Payout("key-a", "acct-1", "t1", 10, WINDOW_START)
        second = Payout("key-b", "acct-1", "t1", 10, WINDOW_START)
        self.assertTrue(self.store.add_payout(first))
        self.assertFalse(self.store.add_payout(second))
        self.assertEqual([p.key for p in self.store.payouts()], ["key-a"])
        self.assertEqual(self.store.total_credits("acct-1"), 10)


if __name__ == "__main__":
    unittest.main()
