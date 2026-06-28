# L3 — Memory System
## Metric · Benchmark · Kết Quả Kỳ Vọng

---

## Phần 1 — Vấn Đề Là Gì? (1 phút đọc)

Sau mỗi giao dịch, hệ thống lưu lại một bản ghi:
- Ngày giao dịch, ticker, quyết định (Buy/Sell/Hold), kết quả lãi/lỗ
- Bài học rút ra

Lần sau phân tích cùng ticker, hệ thống lấy **5 bản ghi gần nhất** đưa cho AI tham khảo.

**Vấn đề**: "Gần nhất theo thời gian" ≠ "Phù hợp nhất với hôm nay".

> Ví dụ: Hôm nay BTC đang **giảm mạnh**. 5 bản ghi gần nhất đều từ giai đoạn BTC **đang tăng**. AI đọc vào và bị bias theo chiều tăng → có thể ra lệnh BUY sai thời điểm.

---

## Phần 2 — Metric Bị Ảnh Hưởng

| Metric | Vì sao bị ảnh hưởng? |
|---|---|
| **Win Rate** (% giao dịch thắng) | Memory sai chiều → AI bị bias → quyết định sai hướng thường xuyên hơn |
| **Cumulative Return** (tổng lợi nhuận %) | Win rate thấp trực tiếp kéo tổng lợi nhuận xuống |
| **Alpha** (vượt trội so với benchmark) | Quyết định theo momentum cũ thay vì tình huống thực → underperform thị trường |

> **Metric KHÔNG bị ảnh hưởng nhiều**: Max Drawdown, Sharpe Ratio — vì vấn đề này về chất lượng quyết định, không phải về quản lý rủi ro.

---

## Phần 3 — Kế Hoạch Benchmark

### 3.1 Áp dụng cho loại tài sản nào?

| Asset | Có bị ảnh hưởng? | Lý do |
|---|---|---|
| **Stock** | ✅ Có | Memory dùng chung, logic FIFO không phân biệt |
| **Crypto** | ✅ Có | Như trên, thậm chí nghiêm trọng hơn vì crypto biến động mạnh hơn → regime thay đổi nhanh hơn |

---

### 3.2 Benchmark cho Stock

**So sánh với**: Paper gốc TradingAgents (arxiv 2412.20138)

| Thông số | Giá trị |
|---|---|
| Tickers test | AAPL, NVDA (dùng đúng tickers của paper) |
| Thời gian | 2024-01-01 → 2024-06-30 |
| Tần suất trade | Weekly (mỗi tuần 1 quyết định) |
| Holding period | 5 ngày (giữ nguyên config hiện tại) |
| Benchmark index | SPY (S&P 500) |
| Phương pháp | Chạy backtest tuần theo tuần, mỗi lần gọi `graph.propagate()` |

**Số liệu cần thu thập — Trước cải tiến (baseline)**:

Chạy với config hiện tại (`memory = flat markdown, FIFO`), ghi lại:

```
- Danh sách quyết định: [date, ticker, signal, actual_return_5d]
- Win Rate = số trades có return > 0 / tổng trades
- Cumulative Return = tích lũy return qua các trades
- Alpha vs SPY = cumulative_return - SPY_return cùng kỳ
```

**Số liệu cần thu thập — Sau cải tiến**:

Chạy lại đúng cùng điều kiện với `memory = vector search + regime filter`, ghi lại cùng metrics.

**Bảng so sánh mục tiêu (Stock)**:

| Metric | Paper SOTA (đã biết) | CryptoAgents v1 Baseline | Sau L3 Fix | Mục tiêu |
|---|---|---|---|---|
| Win Rate | **~55–62%** | Cần đo | Cần đo | **Vượt paper SOTA > 62%** |
| Cumulative Return | **~25–35%** | Cần đo | Cần đo | **> 35%** |
| Alpha vs SPY | **~+10–15%** | Cần đo | Cần đo | **> +15%** |

---

### 3.3 Benchmark cho Crypto

**So sánh với**: CryptoAgents v1 (không có paper → phải tự đo baseline)

| Thông số | Giá trị |
|---|---|
| Tickers test | BTC-USD, ETH-USD |
| Thời gian | 2024-01-01 → 2024-06-30 |
| Tần suất trade | Weekly |
| Holding period | 5 ngày |
| Benchmark index | BTC-USD (đã config trong `benchmark_map`) |
| Phương pháp | Giống stock, thêm flag `asset_type="crypto"` |

**Bảng so sánh mục tiêu (Crypto)**:

| Metric | Buy & Hold BTC | CryptoAgents v1 Baseline | Sau L3 Fix | Mục tiêu |
|---|---|---|---|---|
| Win Rate | N/A | Cần đo | Cần đo | **Baseline + 5–8%** |
| Cumulative Return | ~150% (2024 thực tế) | Cần đo | Cần đo | **> Buy & Hold** |
| Alpha vs BTC | 0% | Cần đo | Cần đo | **Baseline + 3–5%** |

---

## Phần 4 — Kết Quả Kỳ Vọng

### Cơ chế tạo ra cải thiện

```
Cũ: Memory FIFO
  Ngày 20/06 (BTC đang giảm) → lấy 5 bản ghi gần nhất
  → 5 bản ghi đều từ giai đoạn tăng (tuần trước)
  → AI bị bias BUY → ra lệnh BUY → thua lỗ
  → Win Rate thấp

Mới: Memory Vector Search + Regime Filter
  Ngày 20/06 (BTC đang giảm, regime=bear) → tìm kiếm tương đồng
  → Tìm thấy bản ghi từ 3 tháng trước khi BTC cũng giảm
  → Bài học: "Giảm vị thế hoặc HOLD trong bear regime"
  → AI ra lệnh HOLD → tránh thua lỗ
  → Win Rate tăng
```

### Kỳ vọng định lượng

| Metric | Stock — Cải thiện | Crypto — Cải thiện |
|---|---|---|
| Win Rate | **+4–7%** so với baseline | **+5–8%** so với baseline |
| Cumulative Return | **+8–12%** tuyệt đối | **+10–15%** tuyệt đối |
| Alpha | **+3–5%** | **+3–5%** |

> **Lưu ý**: Crypto kỳ vọng cải thiện nhiều hơn stock vì crypto biến động mạnh hơn, nên việc nhầm lẫn regime gây hậu quả nặng hơn.

---

## Phần 5 — Điều Kiện Để Kết Quả Hợp Lệ

Để đảm bảo so sánh công bằng, cần **giữ nguyên tất cả** các yếu tố khác:

| Yếu tố | Phải giữ nguyên |
|---|---|
| LLM model | Cùng model (ví dụ GPT-4o) |
| Analysts được dùng | Cùng danh sách |
| Debate rounds | Cùng `max_debate_rounds=1` |
| Tickers & dates | Cùng nhau |
| Holding period | 5 ngày |

**Chỉ thay đổi duy nhất**: Cơ chế memory (FIFO → Vector Search).
