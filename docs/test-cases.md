# Test cases and results

Window for `RUN_AT = 2026-10-13T09:00Z` (a Tuesday): `[2026-10-05T00:00Z, 2026-10-12T00:00Z)`. All data is synthetic.
Automated in `tests/test_settlement.py`; method names carry the case ID. "Legacy" is the faulty fixture.
Ledgers: **memory** (dict) and **SQLite** (real `PRIMARY KEY` + `UNIQUE(task_id)`), selected with `REWARDS_STORE`.
Actual results are in `docs/evidence/` (run on Windows, Python 3.11.6): `suite-fixed.txt`, `suite-legacy.txt`,
`suite-fixed-sqlite.txt`, `suite-legacy-sqlite.txt`, `run_checks.txt`.

| ID | Category | Input | Expected | Fixed | Legacy (memory) |
|----|----------|-------|----------|-------|-----------------|
| TC-01 | Happy path | 3 completed in-window tasks (acct-1 x2, acct-2 x1) | 3 payouts; acct-1 = 20, acct-2 = 10 credits; 3 notifications, all for existing payouts | pass | pass |
| TC-02 | Boundary (lower) | task at `10-05T00:00:00Z`; task at `10-04T23:59:59Z` | first paid, second not | pass | pass |
| TC-03 | Boundary (upper) | task at `10-11T23:59:59Z`; task at `10-12T00:00:00Z`; then next week's run with same list | first paid; boundary task not paid in this run, paid exactly once in next | pass | pass |
| TC-04 | Timezone (task) | `10-12T02:59+03:00` (=10-11T23:59Z), `10-11T23:30-02:00` (=10-12T01:30Z), `10-05T03:00+03:00` (=10-05T00:00Z), `10-05T02:59+03:00` (=10-04T23:59Z) | paid: 1st and 3rd only | pass | pass |
| TC-05 | Timezone (run) | run at `10-13T12:00+03:00` | same window as 09:00Z; task paid | pass | pass |
| TC-06 | Invalid input | one valid task + one naive datetime | `ValueError`; zero payouts | pass | pass |
| TC-07 | Eligibility | one completed, one `in_progress` | only completed paid and notified; other reported `not_completed` | pass | pass |
| TC-08 | Admin/account | task of blocked account | not paid; reported `account_blocked` | pass | pass |
| TC-09 | Empty | no tasks | no payouts, no notification attempts | pass | pass |
| TC-10 | **Duplicate input** | `dup`, `dup`, `other` | `dup` paid once, 20 credits total | pass | **FAIL** `['dup','dup','other']` |
| TC-11 | Duplicate (conflicting) | `dup` completed after window end + `dup` mid-window | earliest wins: paid once | pass | pass (incidental: late copy is out of window) |
| TC-12 | **Retry** | settle `[t1,t2]`, then settle again with same input | still 2 payouts, 20 credits; no new notifications | pass | **FAIL** `['t1','t1','t2','t2']` |
| TC-13 | **Re-appearance** | `t1` paid this week; same ID with a next-window timestamp in next run | still one payout | pass | **FAIL** `['t1','t1']` |
| TC-14 | **Config change on retry** | settle at 10 credits, retry at 20 | total stays 10 | pass | **FAIL** `30 != 10` |
| TC-15 | **Partial failure (crash)** | 4 tasks, store crashes on 3rd insert, then retry | exactly 4 payouts, 40 credits, each notified once, no notification without payout | pass | **FAIL** 6 payouts |
| TC-16 | Partial failure (notify) | notifier fails for `t2` | 3 payouts remain, 30 credits; failure reported; 2 delivered | pass | pass |
| TC-17 | **Retry after notify failure** | TC-16 then retry with healthy notifier | only `t2` re-sent; payouts unchanged | pass | **FAIL** re-paid, 3 attempts |
| TC-18 | **Crash after send, before mark_notified** | 2 tasks; `mark_notified` raises after the first `send`; then retry | payouts stay 2 (20 credits); retry re-sends `t1` and `t2` (documented at-least-once); nothing sent without a payout | pass | **FAIL** re-paid |
| TC-19 | **Admin change (unblock) + re-run** | `good`, `bad` (blocked acct); run; unblock; run twice more | `bad` paid once after unblock; `good` stays paid once; 10 credits each | pass | **FAIL** `good` paid 3 times |
| TC-20 | **Concurrency** | 6 threads run the same window at the same moment over 20 tasks (SQLite ledger) | 20 payouts, 200 credits, every task notified at least once, none notified without a payout, no thread errors | pass (8 of 8 repeat runs) | **FAIL** notifications for payouts that do not exist |
| TC-21 | **DB constraint** | insert payout `key-a` for `t1`, then `key-b` for the same `t1` (SQLite ledger) | second insert rejected; one row; 10 credits | pass | pass (tests the ledger, not the settlement code) |

Totals (memory ledger): fixed 21/21 pass. Legacy 12 pass, 9 fail (TC-10, 12, 13, 14, 15, 17, 18, 19, 20).
Totals (SQLite ledger): fixed 21/21 pass. Legacy 16 pass, 5 fail (TC-12, 15, 17, 18, 20).
On SQLite the `UNIQUE(task_id)` constraint blocks the second payout, so legacy no longer double-pays in the
ledger, but it still reports payouts that were not created and sends notifications for payouts that do not
exist (BR-6 violation). That is why the constraint is a safety net and not a substitute for the fix.

## Mutation checks (`run_checks.py`)

| Mutant of the fixed code | Ledger | Result |
|--------------------------|--------|--------|
| Upper boundary included | memory | killed (TC-03) |
| Lower boundary excluded | memory | killed (TC-02 and 2 more) |
| UTC offset ignored | memory | killed (TC-04) |
| Payout key scoped to attempt (the real defect, re-injected) | memory | killed (7 tests) |
| Payout reversed on notification failure | memory | killed (TC-16) |
| Database `PRIMARY KEY` / `UNIQUE` constraints dropped from the schema | SQLite | killed (9 tests, incl. TC-12, TC-20, TC-21) |
| Input de-duplication removed | memory | **survived**: equivalent mutant. The ledger's unique key already collapses duplicate rows, so de-dup is defence in depth, not the primary guard. |
