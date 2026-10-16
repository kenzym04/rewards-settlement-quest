"""Test doubles: recording notifier with failure injection, crashing stores, store selection."""

import importlib
import itertools
import os
from typing import Iterable, List

from rewards.models import Payout
from rewards.notifier import NotificationError
from rewards.sqlite_store import SqliteStore
from rewards.store import Store

IMPLEMENTATIONS = {
    "fixed": "rewards.settlement",
    "legacy": "rewards.legacy_settlement",
}

STORE_KINDS = ("memory", "sqlite")

_LEDGER_FILES = itertools.count(1)


def load_impl():
    """Select the implementation under test with REWARDS_IMPL=fixed|legacy (default fixed)."""
    name = os.environ.get("REWARDS_IMPL", "fixed")
    if name not in IMPLEMENTATIONS:
        raise RuntimeError("REWARDS_IMPL must be one of %s" % sorted(IMPLEMENTATIONS))
    return importlib.import_module(IMPLEMENTATIONS[name])


def make_store(directory: str):
    """Build the ledger selected by REWARDS_STORE=memory|sqlite (default memory)."""
    kind = os.environ.get("REWARDS_STORE", "memory")
    if kind not in STORE_KINDS:
        raise RuntimeError("REWARDS_STORE must be one of %s" % list(STORE_KINDS))
    if kind == "memory":
        return Store()
    return SqliteStore(os.path.join(directory, "ledger-%d.db" % next(_LEDGER_FILES)))


class StoreCrash(Exception):
    """Simulates the process dying in the middle of a run."""


class _StoreProxy:
    """Delegates everything to a real store; subclasses add one injected crash."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._armed = True

    def disarm(self) -> None:
        self._armed = False

    def __getattr__(self, name):
        return getattr(self._inner, name)


class CrashingStore(_StoreProxy):
    """add_payout raises on the Nth call until disarm() is called."""

    def __init__(self, inner, crash_on_call: int) -> None:
        super().__init__(inner)
        self._crash_on_call = crash_on_call
        self._calls = 0

    def add_payout(self, payout: Payout) -> bool:
        self._calls += 1
        if self._armed and self._calls == self._crash_on_call:
            raise StoreCrash("simulated crash on add_payout call %d" % self._calls)
        return self._inner.add_payout(payout)


class CrashAfterSendStore(_StoreProxy):
    """mark_notified raises on its first call until disarm(): the process dies after send()."""

    def mark_notified(self, key: str) -> None:
        if self._armed:
            raise StoreCrash("simulated crash after send, before mark_notified(%s)" % key)
        self._inner.mark_notified(key)


class RecordingNotifier:
    """Records deliveries; flags any notification sent for a payout missing from the store."""

    def __init__(self, store, failing_task_ids: Iterable[str] = ()) -> None:
        self._store = store
        self._failing = set(failing_task_ids)
        self.attempted: List[str] = []
        self.sent: List[str] = []
        self.sent_without_payout: List[str] = []

    def send(self, payout: Payout) -> None:
        self.attempted.append(payout.task_id)
        if payout.task_id in self._failing:
            raise NotificationError("simulated delivery failure for %s" % payout.task_id)
        if not self._store.has_payout(payout.key):
            self.sent_without_payout.append(payout.task_id)
        self.sent.append(payout.task_id)
