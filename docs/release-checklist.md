# Release-readiness checklist

Scope: the fixed reference implementation in this repository, **as a test fixture**. Not a production financial system.

| # | Check | Evidence | Status |
|---|-------|----------|--------|
| 1 | All 21 cases pass on `fixed` with the in-memory ledger | `docs/evidence/suite-fixed.txt` | PASS |
| 2 | All 21 cases pass on `fixed` with the SQLite ledger (real constraints) | `docs/evidence/suite-fixed-sqlite.txt` | PASS |
| 3 | Same suite fails on `legacy` for the targeted defect (9 failures memory, 5 SQLite) | `suite-legacy.txt`, `suite-legacy-sqlite.txt` | PASS |
| 4 | Mutants for boundary, timezone, key, notify-rollback and dropped DB constraint are killed | `docs/evidence/run_checks.txt` | PASS |
| 5 | Surviving mutants explained | equivalent mutant (de-dup) documented | PASS |
| 6 | Business rules and assumptions written | `docs/business-rules.md` | PASS |
| 7 | UNIQUE constraints enforced by a real database engine | SQLite: TC-12, 20, 21 and the dropped-constraint mutant | PASS (SQLite only) |
| 8 | Concurrent runs for the same window | TC-20: 6 threads, 20 tasks, 8 of 8 repeat runs green | PASS (threads, SQLite only) |
| 9 | Crash between `send` and `mark_notified` | TC-18: no double payout; one duplicate notification (at-least-once, accepted and documented) | PASS (behaviour documented) |
| 10 | Admin unblock then re-run | TC-19 | PASS |
| 11 | UNIQUE constraints exist in the production schema / migration | not applicable: no production system | NOT TESTED |
| 12 | Multi-process or network-database concurrency, distributed lock | not built | GAP |
| 13 | Real notification provider behaviour, exactly-once delivery | not in scope; needs outbox or provider idempotency key | GAP |

## Decision

**Fixture/reference: GO** for use as a regression guard for BR-1 to BR-7 as specified.
**Production: NO-GO** until items 11 to 13 are closed (production schema check, multi-process concurrency test, delivery guarantee decision).

## Handoff

1. `python run_checks.py` must exit 0 (about 25 seconds).
2. Never put attempt, run or timestamp values into `payout_key`; never remove the ledger constraints.
3. Next work in priority order: multi-process concurrency test; transactional outbox so pay and notify state change atomically; admin-setting audit trail.
