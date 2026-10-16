"""Settlement window calculation. All comparisons are done in UTC."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
WINDOW_LENGTH = timedelta(days=7)


@dataclass(frozen=True)
class Window:
    """Half-open interval [start, end): start is included, end is excluded."""

    start: datetime
    end: datetime


def to_utc(moment: datetime) -> datetime:
    """Convert an aware datetime to UTC. Naive datetimes are rejected (ambiguous)."""
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("timezone-aware datetime required: %r" % (moment,))
    return moment.astimezone(UTC)


def window_for(run_at: datetime) -> Window:
    """Return the window settled by a run: the 7 days ending at the latest Monday 00:00 UTC.

    A Tuesday 09:00 UTC run settles [previous Monday 00:00, this week's Monday 00:00).
    Any run inside the same UTC week (including retries) maps to the same window.
    """
    run_utc = to_utc(run_at)
    midnight = run_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = midnight - timedelta(days=run_utc.weekday())
    return Window(start=monday - WINDOW_LENGTH, end=monday)


def in_window(moment: datetime, window: Window) -> bool:
    """True when start <= moment < end (upper boundary excluded)."""
    return window.start <= to_utc(moment) < window.end
