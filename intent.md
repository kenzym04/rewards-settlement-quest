# intent.md: Why this problem?

> Fictional brief rules, synthetic data. This submission uses **no real incident data**: no tickets, names, amounts, URLs, or employer material. The failure choices are informed by defect patterns I have seen in real payout flows (sanitized; see "Real-world context" below), but every score here reflects my own judgement, not a measurement.

## Chosen problem

**A settlement retry (or duplicated input row) pays the same task twice.** Rule: a task ID earns 10 test credits at most once, ever.

## Problems considered

Scale: 1 (low) to 5 (high). Effort is the cost of reproducing, fixing, and guarding against the failure (5 = most work).

| **#** | **Failure** | **Impact** | **Likelihood** | **Effort** | **Priority = (I × L) / E** |
| :---- | :--------- | :-------: | :------------: | :--------: | :------------------------: |
| F1 | Retry / crash-resume / duplicate row creates a second payout | 5 | 4 | 3 | **6.7** |
| F2 | Window boundary or timezone error (end included, offset ignored) | 4 | 3 | 2 | 6.0 |
| F3 | Notification failure reverses the payout or notifies an unpaid task | 3 | 3 | 2 | 4.5 |
| F4 | Two runs for the same window at once (race) | 5 | 2 | 5 | 2.0 |
| F5 | Late-arriving tasks and account changes between runs | 3 | 3 | 4 | 2.3 |
| F6 | A record-only status override (e.g., to Failed) on a payout the bank has already accepted unlocks a refund or retry, resulting in the money being paid twice | 5 | 2 | 3 | 3.3 |

## Prioritization criteria

- **Impact:** Money moved incorrectly and how reversible the transaction is. Overpayment is the hardest to recover; a missed payout can be fixed by rerunning the window.
- **Likelihood:** How often the trigger occurs during normal operation. Retries and restarts are routine for scheduled jobs; a boundary timestamp occurring exactly at midnight is rarer.
- **Effort:** The effort required to reproduce, fix, and guard against the failure within the 6–8-hour budget.

## Why F1 ranked first

It has the highest impact and the most likely trigger. F2 is close (6.0 vs. 6.7), so the ranking is sensitive to my scores: if boundary timestamps were far more common than retries, F2 would rank first. I still covered F2 and F3 with tests (TC-02 to TC-05 and TC-16) and mutation checks because the same suite can guard against them cheaply. F1's fix (payout identity = task ID) also contains the damage caused by F2: a task incorrectly included in two windows is still paid only once. F4 (concurrent runs) was initially rejected because of the effort involved; after completing F1, I added a thread-based test (TC-20) using a SQLite ledger because the database constraint made it inexpensive. F5 remains a gap, except for the unblock-and-rerun case (TC-19).

## Real-world context (sanitized)

F6 comes from a defect pattern I have encountered in real payout work: the guard that blocks a refund or retry checks only a **status field**, so an admin who manually flips the status (a record-only change) can unlock a refund or a second bank transfer for money that has already left. I deliberately provide no ticket, system, name, amount, or link: that material is not mine to share, and a reviewer could not access it.

F6 ranks below F1 because it requires a manual admin action (lower likelihood), and reproducing it faithfully requires a bank-state simulator that does not fit the time budget. It belongs to the same family as F1 (a business identity must not be paid twice), but **this project's tests do not cover F6**. That is stated as a gap, not claimed as coverage.

## Affected users (hypothetical, for the fictional service)

- The platform operating the rewards budget (overpayment costs and reconciliation work).
- Task completers (receive credits they should not receive, which may later be clawed back, or see confusing duplicate notifications).
- Support and finance staff (investigation and correction).

## Evidence

- Reproduced with a faulty fixture I built (`legacy_settlement.py`): 9 of 21 tests fail on the in-memory ledger, and 5 of 21 fail on a real SQLite ledger with UNIQUE constraints, all due to one root cause. The fixture is **my model of a plausible defect**, written for this Quest, not a copy of any real incident.
- The fixed version passes 21/21 tests on both ledgers; six mutants are killed (one equivalent mutant survives and is documented). Outputs are in `docs/evidence/`.

## Intended value

A regression check that fails on the first change that allows a task to be paid twice, together with written rules and a release gate that others can run in about 25 seconds.

## Non-goals

- No real payments, accounts, providers, or production deployment.
- No multi-process, network-database, or distributed-lock solution (documented gap). Thread concurrency on SQLite is covered by TC-20.
- No real notification transport, UI, or performance work.
- No claim that the fictional rules reflect any live MUST product.
- No data or documents from any employer system; F6 is described only as a generic pattern.
- No test for F6 (status-override bypass of a refund or retry guard).
