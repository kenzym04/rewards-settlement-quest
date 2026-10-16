"""In-memory ledger. Stands in for a database table with a UNIQUE payout key."""

from datetime import datetime
from typing import Dict, List, Set

from rewards.models import Payout


class Store:
    def __init__(self) -> None:
        self._payouts: Dict[str, Payout] = {}
        self._notified: Set[str] = set()

    def has_payout(self, key: str) -> bool:
        return key in self._payouts

    def add_payout(self, payout: Payout) -> bool:
        """Insert a payout. Returns False (and changes nothing) if the key already exists."""
        if payout.key in self._payouts:
            return False
        self._payouts[payout.key] = payout
        return True

    def payouts(self) -> List[Payout]:
        return [self._payouts[key] for key in sorted(self._payouts)]

    def unnotified_payouts(self, window_start: datetime) -> List[Payout]:
        pending = [
            payout
            for payout in self.payouts()
            if payout.window_start == window_start and payout.key not in self._notified
        ]
        return pending

    def mark_notified(self, key: str) -> None:
        self._notified.add(key)

    def total_credits(self, account_id: str) -> int:
        return sum(p.credits for p in self._payouts.values() if p.account_id == account_id)
