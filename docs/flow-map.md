# Flow map

```mermaid
flowchart TD
    A[Scheduler: Tuesday 09:00 UTC or retry] --> B[window_for run_at -> start, end UTC]
    B --> C[select_eligible: dedupe by task ID, then filter]
    C -->|naive datetime| X[ValueError - nothing paid]
    C --> D{in window? start <= t < end}
    D -- no --> Z[ignored]
    D -- yes --> E{status completed?}
    E -- no --> S1[skipped: not_completed]
    E -- yes --> F{account blocked?}
    F -- yes --> S2[skipped: account_blocked]
    F -- no --> G[pay_tasks: key = task ID, 10 credits]
    G --> H{key already in ledger?}
    H -- yes --> I[no-op: already paid]
    H -- no --> J[insert payout]
    J -->|process crash| R[retry later: resumes at H]
    I --> K[notify_pending: payouts of this window not yet notified]
    J --> K
    K --> L{send ok?}
    L -- yes --> M[mark notified]
    L -- no --> N[stay pending, payout untouched, report failure]
```

## Failure points and where the rule holds

| Step | What can go wrong | Guard |
|------|-------------------|-------|
| Window | Off-by-one at end, wrong timezone | BR-2, BR-3 |
| Input | Duplicate rows, naive timestamps | BR-3, BR-5 |
| Pay | Crash mid-run, retry, re-run | payout key = task ID (BR-5) |
| Notify | Provider down, crash after send | pending state derived from the ledger (BR-7) |
