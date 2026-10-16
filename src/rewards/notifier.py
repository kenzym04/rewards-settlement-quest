"""Notification port. Real transports (email, push) are out of scope."""

from typing import Protocol

from rewards.models import Payout


class NotificationError(Exception):
    """Raised by a notifier when a message could not be delivered."""


class Notifier(Protocol):
    def send(self, payout: Payout) -> None:
        """Deliver a notification for a payout or raise NotificationError."""
