# Business rules (fictional assessment rules, not a live product)

| ID | Rule | Where enforced | Tests |
|----|------|----------------|-------|
| BR-1 | A run settles completed tasks for the window `[previous Monday 00:00 UTC, following Monday 00:00 UTC)`. Scheduled Tuesday 09:00 UTC. | `window.window_for` | TC-01, TC-05 |
| BR-2 | Window start is **included**, window end is **excluded**. | `window.in_window` | TC-02, TC-03 |
| BR-3 | All times are compared in UTC. Offsets on input are converted. Naive (no-offset) datetimes are rejected before any payout. | `window.to_utc` | TC-04, TC-05, TC-06 |
| BR-4 | Each qualifying (status `completed`) task earns 10 test credits. | `settlement.pay_tasks` | TC-01, TC-07 |
| BR-5 | A task ID is paid **at most once, ever**: duplicate input rows, retries, re-runs and re-appearance in a later window never create a second payout. | `settlement.payout_key` (+ ledger uniqueness) | TC-10 to TC-15, TC-18 to TC-21 |
| BR-6 | A notification is sent only for a payout that exists in the ledger. | `settlement.notify_pending` | TC-01, TC-07, TC-15, TC-20 |
| BR-7 | A failed notification never reverses or blocks a payout; it stays pending and is retried on the next run for that window, without re-paying. Notifications recorded as delivered are not re-sent. Delivery is at-least-once: if the process dies after `send` and before `mark_notified`, that one notification is sent again on retry (TC-18). | `settlement.notify_pending` | TC-16, TC-17, TC-18 |

## Assumptions (none validated against a real system or stakeholder; chosen by the candidate and AI for this exercise; A2 and A7 are exercised by synthetic tests TC-19 to TC-21)

- A1. Credits per task (10) and the blocked-account list are admin settings read once per run.
- A2. Account state is evaluated at settlement time: tasks of blocked accounts are skipped and reported. Re-running the same window after unblocking pays them once, and never re-pays the others (TC-19).
- A3. A retry after an admin changes credits-per-task does not change already-paid payouts (TC-14).
- A4. Duplicate rows with the same task ID are one task. If rows conflict, the earliest `completed_at` wins (TC-11).
- A5. One notification per payout (not one summary per account).
- A6. "Retry" means calling `settle` again for the same window, any time in the same UTC week.
- A7. The ledger (a DB table in real life) enforces a UNIQUE payout key and a UNIQUE task ID and inserts atomically. The suite runs against two ledgers: an in-memory dict and a SQLite table with real `PRIMARY KEY` and `UNIQUE(task_id)` constraints (TC-20, TC-21). SQLite is a stand-in: its locking and isolation differ from a production database, and no network database was tested.
