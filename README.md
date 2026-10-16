# Rewards settlement: duplicate-payout regression (Quest project)

Fictional, synthetic. Python 3.11+, standard library only. Start with `intent.md`, then `directive.md`.

Run from this folder, in this order. Expected results are in the comments.

```powershell
cls
# clear screen

$env:REWARDS_IMPL="legacy"; $env:REWARDS_STORE="memory"; python -m unittest discover -s tests -t .
# 9 failures. Then open docs/evidence/suite-legacy.txt line 69 (TC-12: t1,t1,t2,t2)

$env:REWARDS_IMPL="legacy"; $env:REWARDS_STORE="sqlite"; python -m unittest discover -s tests -t .
# 5 failures

Remove-Item Env:REWARDS_IMPL,Env:REWARDS_STORE -ErrorAction SilentlyContinue

$env:REWARDS_IMPL="fixed"; $env:REWARDS_STORE="memory"; python -m unittest discover -s tests -t .
# 21 pass (OK)

$env:REWARDS_IMPL="fixed"; $env:REWARDS_STORE="sqlite"; python -m unittest discover -s tests -t .
# 21 pass (OK)

python run_checks.py
# all stages hold; exit 0. Scroll to MUTANTS
```
