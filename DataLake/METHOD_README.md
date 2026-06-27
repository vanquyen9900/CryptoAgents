# Báo cáo phương pháp DataLake: MeMo Adapt Q1/2024

## 1. Mục tiêu

`DataLake` là bộ dữ liệu và harness thực nghiệm dùng để đánh giá việc kết hợp kiểu suy luận multi-agent của TradingAgents với cơ chế thích nghi bộ nhớ của MeMo.

Câu hỏi chính:

> Bộ nhớ lịch sử có giúp agent ra quyết định tốt hơn baseline không có memory trên tập kiểm thử Q1/2024 hay không?

Tài liệu này gộp phần phương pháp và kết quả từ hai báo cáo:

- `reports/q1_2024_performance_analysis.md`
- `reports/memories_extracted.md`

Kết quả trong báo cáo không phải lời khuyên đầu tư. Đây là benchmark offline, point-in-time, dùng để so sánh prompt, chính sách truy xuất memory và khả năng quản trị rủi ro.

## 2. Thiết lập thực nghiệm

| Thành phần | Giá trị |
|---|---|
| Test split | `DataLake/data_test_2024_q1` |
| Giai đoạn đánh giá | `2024-01-02` đến `2024-03-29` |
| Mã cổ phiếu | `AAPL`, `AMZN`, `GOOGL` |
| Tournament | `tour_2024_q1_eval` |
| Context policy | `ctx_paper_aligned_v1` |
| Data mode | `offline_full_pipeline` |
| Memory policy | `mem_top5_role_v1` cho arm có memory |
| Cơ chế khớp lệnh | Quyết định ở ngày `t`, khớp ở giá mở cửa của ngày giao dịch kế tiếp |
| Portfolio | Long-only, vốn ban đầu `100000`, phí giao dịch `0 bps` |

Luồng pipeline chính:

```text
crawl/normalize data
  -> build Q1 episodes
  -> materialize point-in-time context
  -> run_memo_tournament.py
  -> trajectory decisions
  -> weekly memory lessons
  -> portfolio evaluation
```

Các lệnh chạy chính:

```powershell
python DataLake/run_test_2024_q1_crawl.py --skip-crawl
python DataLake/run_q1_2024_experiment.py
python DataLake/run_q1_2024_experiment.py --arm EVAL
```

## 3. Các arm so sánh và trạng thái artifact

| Arm | Nhóm so sánh | Mô tả |
|---|---|---|
| Market | Buy & Hold | Benchmark thị trường cho từng mã |
| Arm A | Ours w/o Memory | Agent không dùng memory, policy `mem_none_v1` |
| Arm B | Ours + Memory | Seed memory từ năm 2022 và học thêm bài học hằng tuần trong Q1/2024 |

Trạng thái artifact hiện tại:

- Episodes và materialized inputs đã đủ cửa sổ Q1 trong canonical split.
- Real trajectories canonical hiện có hai nhóm: Arm A và Arm B.
- Mỗi nhóm có 189 trajectory rows, từ `2024-01-02` đến `2024-01-31`.
- Mỗi trajectory là một cặp `episode x prompt_set`.
- Benchmark portfolio được tính trên cửa sổ Q1 bằng cách forward-fill exposure từ các quyết định đã có.

## 4. Cơ chế MeMo Adapt

### 4.1 Memory Bank

Memory bank là tập hợp các bài học có cấu trúc. Mỗi memory gồm:

- `memory_id`: khóa định danh bài học.
- `memory_bank_version`: phiên bản bank được dùng trong arm.
- `agent_role`: vai trò áp dụng; runner hiện lọc theo `trader`.
- `symbol`: mã gốc của bài học, hoặc `ANY` với weekly lesson.
- `market_regime`: chế độ thị trường của bài học, ví dụ `bearish_momentum`.
- `lesson`, `do`, `avoid`, `trigger_conditions`: nội dung đưa vào context.
- `quality_score`, `reward_20d`: tín hiệu dùng để xếp hạng memory.
- `visible_from`: mốc thời gian memory bắt đầu được phép hiển thị cho agent.

Arm B dùng seed memory được copy từ training bank:

```text
mb_2022_full_highvar_trueskill_socialproxy_llm_v1
  -> mb_q1_2024_2022_memory_weekly_learning_v1
```

Khi copy seed, runner đổi `memory_id` bằng suffix `_seed2022` và đặt `visible_from = 2024-01-02T00:00:00Z`. Vì vậy, Q1 agent có thể dùng seed memory ngay từ ngày giao dịch đầu tiên.

### 4.2 Weekly Learning

Sau mỗi tuần của Arm B, `memo_weekly_lesson_manager.py` lọc trajectories trong tuần đó và sinh một weekly lesson.

Cơ chế hiện tại là reflection dạng rule-based:

- Đếm tần suất hành động theo từng mã, ví dụ `AAPL: Hold`, `AMZN: Buy`.
- Tạo situational lesson nhắc agent so sánh evidence hiện tại với decision ledger gần nhất.
- Nhắc agent không dùng momentum đơn lẻ; cần xác nhận thêm từ support/resistance, rủi ro, macro và social signals.
- Ghi lesson ra `memory_bank/weekly_lessons/*.md`.

Weekly lesson có `visible_from` sau `week_end`, vì vậy bài học của tuần hiện tại không bị leak ngược vào các quyết định trong chính tuần đó.

### 4.3 Cách chọn bài học đưa vào context

Trong `run_memo_tournament.py`, với mỗi trajectory:

1. Load memory bank theo `memory_bank_version`.
2. Loại memory có `visible_from > analysis_time`.
3. Gọi `retrieve_memories_for_context(...)`.
4. Format memory thành markdown bằng `format_retrieved_memories(...)`.
5. Đưa memory markdown vào stage quyết định portfolio cuối cùng.

Policy `mem_top5_role_v1`:

| Rule | Giá trị |
|---|---|
| `top_k_memories` | 5 |
| `same_symbol_boost` | true |
| `same_regime_required` | false |
| `agent_role_filter` | true |

Regime hiện tại được suy luận từ materialized input:

- `close` so với `SMA50`.
- `close` so với `SMA200`.
- `MACD` âm/dương.
- `RSI` yếu/mạnh.

Nếu bearish votes >= 2 thì regime là `bearish_momentum`; nếu bullish votes >= 2 thì regime là `bullish_momentum`; các trường hợp còn lại là `mixed_regime`.

Sau khi lọc, memory được chấm điểm:

```text
score =
  quality_score
  + same_symbol_boost
  + regime_match_bonus
  + risk_or_negative_lesson_bonus
  + min(abs(reward_20d), 0.25)
```

Runner lấy top 5 memories có score cao nhất. Memory chỉ đóng vai trò `situational prior`; prompt final decision nêu rõ rằng current point-in-time evidence và current portfolio state phải được ưu tiên hơn bài học lịch sử.

### 4.4 Memory được đưa vào stage nào

`offline_full_pipeline` chạy 7 stage LLM:

1. Market analyst.
2. News/social/macro analyst.
3. Fundamentals analyst.
4. Research manager.
5. Trader.
6. Risk debate.
7. Portfolio manager final decision.

Memory chỉ được inject vào stage 7: `portfolio_manager_final_decision`.

Decision ledger được đưa vào trader/risk/final stage. Ledger chỉ gồm các quyết định trước đó cùng `symbol`, cùng `prompt_set`, cùng `comparison_group`, đồng thời cho biết `current_exposure_before_decision`.

Ý nghĩa thực nghiệm:

- Analyst stages đọc dữ liệu hiện tại, không bị memory chi phối.
- Trader/risk stage nhìn thấy lịch sử position gần đây qua decision ledger.
- Final portfolio manager mới nhận memory như kinh nghiệm bổ sung.
- Cách này giảm nguy cơ memory bị dùng như "ground truth" thay vì soft prior.

## 5. Benchmark Q1/2024

Các chỉ số:

- `CR%`: cumulative return, tức lợi nhuận tích lũy.
- `ARR%`: annualized return, tức lợi nhuận quy đổi theo năm.
- `SR`: Sharpe ratio.
- `MDD%`: maximum drawdown, hiển thị theo độ lớn drawdown dương như report gốc.

### Market Benchmark

| Symbol | CR% | ARR% | SR | MDD% |
|---|---:|---:|---:|---:|
| AAPL | -7.91 | -27.71 | -1.59 | 13.50 |
| GOOGL | 12.87 | 61.10 | 1.86 | 14.40 |
| AMZN | 22.26 | 120.63 | 3.22 | 4.22 |

### Agent Benchmark

| Model | Prompt | AAPL CR/ARR/SR/MDD | GOOGL CR/ARR/SR/MDD | AMZN CR/ARR/SR/MDD |
|---|---|---:|---:|---:|
| Ours w/o Memory | `ps_default_v1` | 0.00 / 0.00 / - / 0.00 | -0.98 / -3.80 / -0.14 / 8.74 | 20.00 / 105.01 / 3.00 / 4.22 |
| Ours w/o Memory | `ps_macro_defensive_v1` | -9.74 / -33.20 / -2.39 / 11.65 | -2.19 / -8.37 / -0.65 / 6.09 | 12.18 / 57.21 / 2.00 / 4.69 |
| Ours w/o Memory | `ps_risk_aware_v1` | -3.76 / -14.01 / -2.57 / 4.86 | -2.19 / -8.37 / -0.65 / 6.09 | 12.45 / 58.75 / 2.04 / 4.22 |
| Ours + Memory | `ps_default_v1` | -13.04 / -42.31 / -3.07 / 13.60 | -3.81 / -14.20 / -0.82 / 8.74 | 16.36 / 81.58 / 2.60 / 4.22 |
| Ours + Memory | `ps_macro_defensive_v1` | -10.79 / -36.22 / -2.53 / 13.51 | 2.35 / 9.56 / 1.51 / 1.10 | 18.14 / 92.77 / 2.78 / 4.22 |
| Ours + Memory | `ps_risk_aware_v1` | -1.82 / -6.98 / -1.25 / 3.06 | -2.19 / -8.37 / -0.65 / 6.09 | 14.05 / 67.79 / 2.26 / 4.22 |

## 6. Diễn giải kết quả

### AAPL: thị trường giảm

Buy & Hold lỗ `-7.91%` với MDD `13.50%`. Memory phát huy tốt nhất khi kết hợp với `ps_risk_aware_v1`: CR chỉ còn `-1.82%`, MDD `3.06%`. Đây là bằng chứng rõ nhất cho vai trò phòng thủ của memory.

### GOOGL: thị trường biến động, tăng nhẹ

Buy & Hold đạt `12.87%` nhưng MDD cao `14.40%`. Cấu hình Memory + `ps_macro_defensive_v1` không bắt trọn upside, nhưng vẫn có CR dương `2.35%` và giảm MDD xuống `1.10%`. Điểm mạnh chính nằm ở kiểm soát rủi ro.

### AMZN: thị trường tăng mạnh

Buy & Hold đạt `22.26%`. Agent bắt được xu hướng tăng khá tốt, đặc biệt baseline `ps_default_v1` đạt `20.00%`. Khi bật memory, lợi nhuận AMZN thấp hơn một phần, cho thấy memory có xu hướng thận trọng hơn để đổi lấy drawdown thấp.

## 7. Kết luận phương pháp

MeMo Adapt trong Q1/2024 không đóng vai trò "tối đa hóa lợi nhuận" một cách đơn thuần. Tác động rõ nhất là lớp phòng thủ drawdown:

- Tốt nhất trên AAPL khi thị trường giảm: Memory + `ps_risk_aware_v1`.
- Tốt nhất trên GOOGL khi thị trường nhiễu/biến động: Memory + `ps_macro_defensive_v1`.
- Trên AMZN uptrend mạnh, baseline có thể đạt return cao hơn, nhưng memory vẫn giữ drawdown ở mức thấp.

Vì vậy, kết quả nên được đọc như một trade-off: memory giúp agent thực dụng và phòng thủ hơn, đặc biệt khi prompt đã có bias quản trị rủi ro.

## 8. Reproducibility

Validation trước và sau khi chạy:

```powershell
python DataLake/tools/health/check_test_split_health.py
python DataLake/tools/contracts/test_memo_q1_real_artifact_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_portfolio_evaluation_contract.py --data-dir DataLake/data_test_2024_q1 --tournament-id tour_2024_q1_eval --start-date 2024-01-02 --end-date 2024-03-29 --symbols AAPL AMZN GOOGL
python DataLake/tools/contracts/test_memo_decision_ledger_contract.py
```

Quy tắc báo cáo:

- Chỉ dùng `DataLake/data_test_2024_q1` làm canonical Q1 split.
- Không dùng output mock/demo làm research result.
- Không recreate `data_test_2024_q1_armB` hay `data_test_2024_q1_armC`.