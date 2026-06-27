# DataLake Tools

Root `DataLake` keeps only the primary entrypoints:

```powershell
python DataLake/run_test_2024_q1_crawl.py
python DataLake/run_q1_2024_experiment.py
python DataLake/run_memo_tournament.py
```

Supporting tools live here:

- `health/`: dataset health checks.
- `validation/`: dataset, context, tournament, and portfolio validators.
- `contracts/`: contract tests for Q1 artifacts and integration behavior.
- `summarize/`: tournament run/score summarizers.
- `data/`: full crawler/builder orchestration helper.
- `legacy/`: older orchestration scripts kept for reference or manual use.
- `demo/`: mock/demo artifact generator; do not use its output as research results.

Common checks:

```powershell
python DataLake/tools/health/check_test_split_health.py
python DataLake/tools/contracts/test_memo_q1_real_artifact_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_portfolio_evaluation_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --start-date 2024-01-02 --end-date 2024-03-29 --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_decision_ledger_contract.py
```
