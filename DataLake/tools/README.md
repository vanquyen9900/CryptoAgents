# Công cụ hỗ trợ DataLake

Root `DataLake` chỉ giữ các entrypoint chính:

```powershell
python DataLake/run_test_2024_q1_crawl.py
python DataLake/run_q1_2024_experiment.py
python DataLake/run_memo_tournament.py
```

Các công cụ hỗ trợ được đặt trong thư mục này:

- `health/`: kiểm tra sức khỏe dataset và test split.
- `validation/`: kiểm tra dataset, context, tournament và portfolio outputs.
- `contracts/`: contract tests cho artifact Q1 và hành vi tích hợp.
- `summarize/`: script tổng hợp run và score của tournament.
- `data/`: helper điều phối crawler/builder đầy đủ.
- `legacy/`: script orchestration cũ, giữ lại để tham khảo hoặc chạy thủ công.
- `demo/`: generator mock/demo artifact; không dùng output ở đây làm kết quả nghiên cứu.

Các lệnh kiểm tra thường dùng:

```powershell
python DataLake/tools/health/check_test_split_health.py
python DataLake/tools/contracts/test_memo_q1_real_artifact_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_portfolio_evaluation_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --start-date 2024-01-02 --end-date 2024-03-29 --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_decision_ledger_contract.py
```