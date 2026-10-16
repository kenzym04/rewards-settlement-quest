# directive.md (final)

## Objective

Guarantee that the rewards settlement pays each task ID **at most once**, regardless of how often a run is retried, resumed after a crash, rerun, executed concurrently, or supplied with duplicate rows, while preserving the window, timezone, and notification rules.

## Scope

In scope: window calculation, eligibility, payouts that cannot pay the same task twice, notification isolation, a faulty fixture, a corrected implementation, an in-memory ledger, a SQLite ledger with real `PRIMARY KEY` / `UNIQUE(task_id)` constraints, regression testing, concurrency testing (threads), mutation checks (re-injecting plausible bugs), a defect report, and a release checklist.

Out of scope: real money, real providers, multi-process or network-database concurrency, distributed locks, UI, and production deployment.

## Requirements

Rules BR-1 to BR-7 and assumptions A1 to A7 are documented in [docs/business-rules.md](docs/business-rules.md). In summary:

1. Window: starts on Monday at 00:00 UTC (that instant is included) and ends on the next Monday at 00:00 UTC (that instant is excluded and is paid the following week). Written `[Monday 00:00 UTC, next Monday 00:00 UTC)`. The scheduled run is Tuesday 09:00 UTC. Timezone offsets are converted; timestamps with no timezone are rejected.
2. Each completed task earns 10 test credits.
3. Payout identity is the task ID. Never include the attempt, run, or time in the key. If that key already exists, the insert does nothing. The ledger also enforces uniqueness through constraints.
4. Notifications are sent only for payouts already stored. Notification failure never reverses or blocks a payout. A retry resends only notifications not recorded as delivered. A crash after `send` and before `mark_notified` can send that one notification again (at-least-once, not exactly-once).
5. All input is validated before the first payout.

## Completion criteria

- [x] At least three failures ranked, with one selected: [intent.md](intent.md)
- [x] At least eight cases with inputs and expected outcomes (21 written): [docs/test-cases.md](docs/test-cases.md)
- [x] The suite fails on the faulty fixture and passes on the fix, using both ledgers: `python run_checks.py` exits with code 0.
- [x] Defect report covering reproduction, root cause, evidence, fix, and blocking checks: [docs/defect-report.md](docs/defect-report.md)
- [x] Release decision and handoff: [docs/release-checklist.md](docs/release-checklist.md)
- [x] Loom recording (maximum 5 minutes): [https://www.loom.com/share/88bedb959fb34ec6adbeb73344a4efa7](https://www.loom.com/share/88bedb959fb34ec6adbeb73344a4efa7)

---

# Appendix: Results and handoff

## Artifacts

| **Artifact** | **Location** |
| :--- | :--- |
| Runnable test project | `src/rewards/`, `tests/`, `run_checks.py` |
| Faulty fixture / corrected implementation | `src/rewards/legacy_settlement.py` / `src/rewards/settlement.py` |
| Ledgers | `src/rewards/store.py` (memory), `src/rewards/sqlite_store.py` (SQLite, real constraints) |
| 21 test cases and results | [docs/test-cases.md](docs/test-cases.md) |
| Defect and root cause | [docs/defect-report.md](docs/defect-report.md) |
| Release checklist | [docs/release-checklist.md](docs/release-checklist.md) |
| Flow map | [docs/flow-map.md](docs/flow-map.md) |
| Raw run output | `docs/evidence/`: `run_checks.txt`, `suite-fixed.txt`, `suite-legacy.txt`, `suite-fixed-sqlite.txt`, `suite-legacy-sqlite.txt` |
| Loom | [https://www.loom.com/share/88bedb959fb34ec6adbeb73344a4efa7](https://www.loom.com/share/88bedb959fb34ec6adbeb73344a4efa7) |
| Repository | [https://github.com/kenzym04/rewards-settlement-quest](https://github.com/kenzym04/rewards-settlement-quest) |

## How to reproduce (Python 3.11+, standard library only; no installation required)

```powershell
cd <project folder>
$env:REWARDS_IMPL="legacy"; $env:REWARDS_STORE="memory"; python -m unittest discover -s tests -t .
# 9 failures. Evidence for the selected defect: docs/evidence/suite-legacy.txt line 69
# (TC-12 retry: t1 and t2 are two completed tasks; expected paid once; actual t1, t1, t2, t2)

$env:REWARDS_IMPL="legacy"; $env:REWARDS_STORE="sqlite"; python -m unittest discover -s tests -t .
# 5 failures: unique constraint blocks a second payout row; notifications still go out for missing payouts

Remove-Item Env:REWARDS_IMPL,Env:REWARDS_STORE -ErrorAction SilentlyContinue
$env:REWARDS_IMPL="fixed"; $env:REWARDS_STORE="memory"; python -m unittest discover -s tests -t .   # 21 pass
$env:REWARDS_IMPL="fixed"; $env:REWARDS_STORE="sqlite"; python -m unittest discover -s tests -t .   # 21 pass
python run_checks.py                                   # fail-before, pass-after, and six injected bugs; exit 0
```

## Actual results (run on Windows 11, Python 3.11.6, 2026-10-13)

| **Check** | **Result** |
| :--- | :--- |
| Legacy, in-memory ledger | 21 run, **9 failed** (TC-10, 12, 13, 14, 15, 17, 18, 19, 20) |
| Fixed, in-memory ledger | 21 run, **0 failed** |
| Fixed, SQLite ledger | 21 run, **0 failed**; concurrency test TC-20 also passed in 8 out of 8 repeat runs |
| Legacy, SQLite ledger | 21 run, **5 failed** (TC-12, 15, 17, 18, 20): the database constraint prevents the second payout row, but the legacy implementation still reports payouts it did not create and sends notifications for payouts that do not exist |
| Six plausible bugs re-injected into the fixed code | All six caught (upper boundary included, lower boundary excluded, offset ignored, attempt-scoped key, payout reversed on notification failure, DB constraints dropped) |
| Extra change not caught | Input de-duplication removed. This does not cause a double payout, because the ledger unique key already blocks it. Documented; no fake test. |
| `run_checks.py` exit code | 0 |

## AI contribution and my corrections

- **How I used AI:** I designed the scope (ranked failures, chose F1, set BR-1 to BR-7). I used Cursor, model Grok 4.6, to generate the first draft of the fixture, tests, and documents, then to review the code and extend the ledger. I did not accept the output as-is. I ran every check myself. I rejected treating the database unique constraint as the whole fix: on SQLite the faulty code still fails 5 tests because it notifies for payouts that do not exist.
- My own decisions:
  - I decided to submit this runnable project, using the standard-library `unittest` framework, instead of an earlier draft after a rubric-based review showed that the earlier draft claimed things unsupported by any artifact (see Correction 2).
  - I decided the verdict is: as a test fixture this is ready; as production software it is not. The production schema check, multi-process concurrency, and a delivery guarantee have not been implemented or tested here.
  - I decided to close the gaps I could address with evidence (real DB constraints, concurrency, crash after send, and admin unblock) rather than merely listing them, while keeping the remaining gaps documented.
  - I reviewed the final results by rerunning `python run_checks.py` (exit code 0) and checking the case table and evidence files against the code.
- Corrections made during development:
  1. The initial mutant plan included "de-duplication removed", with the expectation that the tests would catch it. Reasoning about the ledger showed that removing de-duplication cannot cause a double payout, so it is an equivalent mutant. It remains a documented survivor rather than prompting a test that proves nothing.
  2. Report fields initially contained internal payout keys. These were changed to task IDs so that tests assert business identity rather than implementation format.
  3. The legacy fixture validates timestamps up front so that its failures remain focused on the selected defect rather than introducing a second defect.
- **Correction 1, identified by running new tests during development (evidence: `docs/evidence/suite-legacy-sqlite.txt`, TC-18):** The draft defect report stated that the legacy ledger's uniqueness check "never fires". Testing the legacy implementation against the new SQLite ledger showed that this is true only for the in-memory dictionary: the `UNIQUE(task_id)` constraint does fire and blocks the second row, yet five tests still fail because the legacy implementation ignores the return value of `add_payout` and sends notifications for payouts that were never created. I corrected the root-cause text in `docs/defect-report.md`. Separately, writing TC-18 (crash after `send` but before `mark_notified`) showed that the draft BR-7 wording, "delivered notifications are not re-sent", was incorrect. The system provides at-least-once delivery. I corrected BR-7 in `docs/business-rules.md` and documented this behaviour as accepted rather than hiding it.
- **Correction 2, rejection of an earlier AI-assisted draft:** An earlier draft of `directive.md`, `intent.md`, and the Loom script claimed a `pytest` suite (`tests/test_payout.py`), a database `UNIQUE` constraint, a CI pipeline, and a passing concurrency test. A review of that submission folder found only three Markdown files; none of those artifacts existed. I rejected and discarded that draft, then rebuilt every claim based on this project. The DB constraint and concurrency test now exist (`src/rewards/sqlite_store.py`, TC-20, TC-21), and their evidence is in `docs/evidence/`. There is still no CI pipeline.

## Limitations and gaps (honest)

- SQLite is not a production database. Its locking and isolation differ from a networked database. No network database was tested, and the production schema was not checked because there is no production schema to check.
- Concurrency is tested using six threads in one process, across 20 tasks, with SQLite only. No multi-process test, distributed lock, or load test was performed.
- A crash between `send` and `mark_notified` causes that notification to be sent again on retry (at-least-once delivery, TC-18). Exactly-once delivery would require an outbox or a provider idempotency key; neither has been implemented.
- There is no CI pipeline; `python run_checks.py` is run manually.
- The faulty fixture is my model of a plausible defect, written for this Quest, not a record of an actual incident. The mutation checks and the dropped-constraint mutant provide additional evidence independent of the fixture. Severity and likelihood are estimates.
- Assumptions A1 to A7 have not been validated with a real stakeholder. A2 (unblock then re-run) and A7 (ledger uniqueness) are exercised by synthetic tests TC-19 to TC-21.
- Actual effort: **2 h 07 min** (my own figure: 24 h minus 21 h 53 min). Most code and documents were drafted by an AI agent; my time went into direction, review, rubric checks, and corrections. This **excludes** Loom recording (retries, timeouts, and the final take). The brief suggests 6 to 8 hours for hand-built work, so the lower figure reflects extensive AI-assisted drafting.

## Release-readiness decision

As a test fixture, this is **ready** (GO). As production software, it is **not** (NO-GO) until the production schema check, a multi-process concurrency test, and a delivery-guarantee decision are complete (see checklist items 11 to 13).

## Next steps

1. Run a multi-process concurrency test against a networked database.
2. Implement a transactional outbox so that payout and notification state changes are handled atomically (removes the duplicate notification).
3. Integrate `run_checks.py` into CI as a merge gate.
