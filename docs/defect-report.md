# Defect report DR-001: retries and duplicate rows create second payouts

**Context:** fictional rewards service, synthetic data. No real incident history is claimed; severity and likelihood below are reasoned estimates.

| Field | Value |
|-------|-------|
| Component | `rewards.legacy_settlement.settle` (faulty fixture) |
| Severity | **High (S1-equivalent)**: over-payment of credits; hard to claw back once spent |
| Likelihood | **Estimate: medium-high.** Any retry, scheduler double-fire, crash-resume or duplicated input row triggers it. Retries are routine in scheduled jobs. |
| Rule violated | BR-5 (a task ID is paid at most once), BR-6 (notify only existing payouts), indirectly BR-7 |
| Status | Reproduced; fixed in `rewards.settlement` |

## Reproduction steps

```powershell
cd <project folder>
$env:REWARDS_IMPL = "legacy"
python -m unittest tests.test_settlement.TestDuplicatesAndRetries.test_tc12_retry_with_same_input_creates_no_second_payout -v
```

Manual equivalent: call `settle(RUN_AT, [t1, t2], store, notifier)` twice with the same input.

## Expected vs actual

| | Expected | Actual (legacy, in-memory ledger) |
|---|----------|-----------------|
| Retry same input (TC-12) | `['t1','t2']`, 20 credits | `['t1','t1','t2','t2']`, 40 credits |
| Duplicate row (TC-10) | `['dup','other']` | `['dup','dup','other']` |
| Crash after 2 of 4, then retry (TC-15) | 4 payouts, 40 credits | 6 payouts (`t1`, `t2` paid twice) |
| Crash after send, before mark (TC-18) | 2 payouts | `t1` paid twice |
| Unblock + re-run (TC-19) | each task paid once | `good` paid 3 times |
| Retry after notify failure (TC-17) | only `t2` re-notified | all re-paid and re-notified |
| Re-appearance in later window (TC-13) | one payout | two |
| 6 concurrent runs, 20 tasks (TC-20) | 20 payouts, notify only existing payouts | notifications sent for payouts that do not exist |

Against the SQLite ledger the `UNIQUE(task_id)` constraint blocks the second row, so legacy no longer over-pays (TC-10, 13, 14, 19 pass), but TC-12, 15, 17, 18, 20 still fail: the service reports payouts it did not create and notifies for payouts that do not exist.

## Root cause

`legacy_settlement.py` builds the payout key as `attempt-<n>-row-<i>`. The key identifies **this execution and input position**, not **the business entity (task ID)**. The ledger's uniqueness check therefore never fires on an in-memory ledger. There is also no "already paid?" lookup. Completion is never recorded per task, so a crash mid-run leaves no trace that resumes safely. The code also ignores the return value of `add_payout`, so even a ledger that rejects the row does not stop the notification.

## Proposed (and implemented) fix

1. Payout key = `task:<task_id>` (`settlement.payout_key`). The ledger insert is idempotent: an existing key is a no-op.
2. Split into pay phase and notify phase. Pending notifications are derived from the ledger (payouts not marked notified), so a retry resumes notification only.
3. Validate all input before the first payout (no partial runs on bad data).
4. Ledger level: `PRIMARY KEY(key)` and `UNIQUE(task_id)` (`rewards.sqlite_store`). The test `DB UNIQUE constraints dropped` proves the suite notices if the migration is missing.

## Evidence

- `docs/evidence/suite-legacy.txt` (9 failures, memory ledger), `suite-legacy-sqlite.txt` (5 failures), `suite-fixed.txt` and `suite-fixed-sqlite.txt` (21/21 pass), `run_checks.txt` (all stages plus mutants).

## Release checks that would block this failure

1. CI runs `python -m unittest discover -s tests -t .` with `REWARDS_STORE=memory` and `REWARDS_STORE=sqlite`: any red test blocks merge.
2. CI runs `python run_checks.py`: a surviving mutant that is not on the documented allow-list blocks merge.
3. Review rule: any change to `payout_key`, the ledger insert or the schema needs TC-10, 12, 13, 15, 17, 18, 20, 21 green and a second reviewer.
4. Pre-release (not built here): migration check that the production payouts table has the UNIQUE constraints, and a staging dry run with a replayed scheduler trigger.

## Known residual risks

- Delivery is at-least-once: a crash between `send` and `mark_notified` re-sends that one notification (TC-18). Fix path: transactional outbox or provider-side idempotency key.
- Concurrency is tested with threads against SQLite only. No multi-process, network database or distributed lock test.
