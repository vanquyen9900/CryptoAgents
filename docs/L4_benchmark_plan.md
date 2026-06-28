# L4 — Debate System
## Metric · Benchmark · Kết Quả Kỳ Vọng

---

## Phần 1 — Vấn Đề Là Gì? (1 phút đọc)

Trước khi ra quyết định cuối, 2 AI tranh luận với nhau:
- 🐂 **Bull**: tìm lý do nên MUA
- 🐻 **Bear**: tìm lý do không nên MUA

Hiện tại, luôn tranh luận **đúng 2 lượt** rồi dừng — bất kể:
- Tín hiệu đã rõ ràng từ lượt 1 (lãng phí tiền API)
- Hay tín hiệu còn mâu thuẫn gay gắt (quyết định thiếu căn cứ)

> Ví dụ: BTC pump +30%, mọi chỉ số đều xanh → Bull và Bear tranh luận 2 lượt dù đã đồng ý ngay từ đầu. Ngược lại, ngày thị trường hỗn loạn → tranh luận vẫn chỉ 2 lượt dù chưa đủ thông tin để kết luận.

---

## Phần 2 — Metric Bị Ảnh Hưởng

L4 ảnh hưởng đến **2 nhóm metric hoàn toàn khác nhau**:

### Nhóm A — Chất lượng quyết định (khi tín hiệu mâu thuẫn)

| Metric | Vì sao bị ảnh hưởng? |
|---|---|
| **Sharpe Ratio** | Quyết định thiếu căn cứ → sai nhiều hơn → return thấp, risk không giảm → Sharpe thấp |
| **Max Drawdown** | Quyết định sai trong lúc thị trường bất thường → thua lớn hơn → Max Drawdown sâu hơn |

### Nhóm B — Chi phí vận hành (khi tín hiệu rõ ràng)

| Metric | Vì sao bị ảnh hưởng? |
|---|---|
| **LLM API calls / quyết định** | Mỗi lượt tranh luận = 1 lần gọi API = tốn tiền, dù không cần thiết |
| **Thời gian / quyết định (latency)** | Càng nhiều lượt → chờ càng lâu |

> **Metric KHÔNG bị ảnh hưởng nhiều**: Win Rate, Cumulative Return — vì Win Rate phụ thuộc chủ yếu vào chất lượng thông tin đầu vào (L3, L7), không phải số vòng tranh luận.

---

## Phần 3 — Kế Hoạch Benchmark

### 3.1 Áp dụng cho loại tài sản nào?

| Asset | Có bị ảnh hưởng? | Lý do |
|---|---|---|
| **Stock** | ✅ Có | `conditional_logic.py` dùng chung cho cả stock và crypto |
| **Crypto** | ✅ Có | Như trên. Crypto thậm chí cần nhiều debate hơn khi có anomaly |

---

### 3.2 Benchmark cho Stock

**So sánh với**: Paper gốc TradingAgents (arxiv 2412.20138)

| Thông số | Giá trị |
|---|---|
| Tickers test | AAPL, NVDA |
| Thời gian | 2024-01-01 → 2024-06-30 |
| Tần suất trade | Weekly |
| Holding period | 5 ngày |
| Benchmark index | SPY |

**Cần đo thêm** (không có trong paper gốc):

| Metric phụ | Cách đo |
|---|---|
| Avg debate rounds / quyết định | Đọc `investment_debate_state["count"]` từ final state |
| Avg LLM calls / quyết định | Dùng LangGraph callback để đếm |
| Avg latency / quyết định | `time.time()` trước và sau `graph.propagate()` |

**Bảng so sánh mục tiêu (Stock)**:

| Metric | Paper SOTA | v1 Baseline | Sau L4 Fix | Mục tiêu |
|---|---|---|---|---|
| Sharpe Ratio | **~1.3–1.8** | Cần đo | Cần đo | **> 1.8** |
| Max Drawdown | **~−8%** | Cần đo | Cần đo | **< −8%** |
| Avg debate rounds | Không có | Cần đo | Cần đo | **Giảm 30%** (khi tín hiệu rõ) |
| Avg LLM calls | Không có | Cần đo | Cần đo | **Giảm ~30%** |

---

### 3.3 Benchmark cho Crypto

**So sánh với**: CryptoAgents v1 (phải tự đo baseline)

| Thông số | Giá trị |
|---|---|
| Tickers test | BTC-USD, ETH-USD |
| Thời gian | 2024-01-01 → 2024-06-30 |
| Tần suất trade | Weekly |
| Holding period | 5 ngày |
| Benchmark index | BTC-USD |

**Bảng so sánh mục tiêu (Crypto)**:

| Metric | Buy & Hold BTC | v1 Baseline | Sau L4 Fix | Mục tiêu |
|---|---|---|---|---|
| Sharpe Ratio | ~0.8 (BTC 2024) | Cần đo | Cần đo | **Baseline + 0.2–0.4** |
| Max Drawdown | ~−25% (BTC 2024) | Cần đo | Cần đo | **Baseline − 20–30% (tương đối)** |
| Chi phí API/tháng ($) | N/A | Cần đo | Cần đo | **Baseline × 0.7** |

---

## Phần 4 — Kết Quả Kỳ Vọng

### Cơ chế tạo ra cải thiện — Sharpe Ratio

```
Tình huống: Tín hiệu mâu thuẫn (thị trường hỗn loạn)

Cũ (2 lượt cố định):
  Round 1: Bull "nên mua" vs Bear "không nên mua"
  → DỪNG → Research Manager đưa ra kết luận dù chưa đủ thông tin
  → Xác suất sai cao hơn → return thấp, risk cao → Sharpe thấp

Mới (tối đa 3–4 lượt, dừng sớm khi đồng thuận):
  Round 1: Bull vs Bear → còn mâu thuẫn (consensus = 30%)
  Round 2: Bull vs Bear → hội tụ hơn (consensus = 60%)
  Round 3: Bull vs Bear → đồng thuận đủ (consensus = 78% > 75%)
  → DỪNG → Research Manager có đủ thông tin
  → Xác suất đúng cao hơn → Sharpe tăng
```

### Cơ chế tạo ra cải thiện — Chi phí API

```
Tình huống: Tín hiệu rõ ràng (thị trường bình ổn, xu hướng rõ)

Cũ (2 lượt cố định):
  Round 1: Bull tự tin 88%, Bear chỉ tự tin 15% (gần như đồng ý BUY)
  Round 2: Tranh luận thêm dù kết quả đã rõ ← LÃng phí
  → 2× chi phí API

Mới (dừng sớm khi conviction > 85%):
  Round 1: Bull 88% → phát hiện một bên > 85% → DỪNG ngay
  → 1× chi phí API (tiết kiệm 50%)
```

### Cơ chế tạo ra cải thiện — Max Drawdown (Crypto anomaly)

```
Tình huống: BTC bị flash crash −15% trong 1 ngày

Cũ:
  Quantitative Analyst báo: "ANOMALY DETECTED"
  → Risk debate vẫn 3 lượt bình thường
  → Portfolio Manager không nhận ra mức độ nguy hiểm
  → Có thể giữ nguyên vị thế → thua lỗ lớn → Max Drawdown sâu

Mới:
  Quantitative Analyst báo: "ANOMALY DETECTED"
  → Risk debate tự động tăng lên 6 lượt
  → 3 risk analysts thảo luận kỹ hơn về mức độ nguy hiểm
  → Portfolio Manager nhận ra risk cao → giảm vị thế hoặc SELL
  → Tránh thua lỗ lớn → Max Drawdown giảm
```

### Kỳ vọng định lượng tổng hợp

| Metric | Stock — Cải thiện | Crypto — Cải thiện |
|---|---|---|
| Sharpe Ratio | **+0.2–0.4** | **+0.2–0.4** |
| Max Drawdown | **−15–25%** (tương đối) | **−20–30%** (tương đối) |
| Chi phí API | **−25–35%** | **−25–35%** |
| Latency/quyết định | **−20–30%** (khi tín hiệu rõ) | **−20–30%** |

> **Ví dụ tính toán**: Nếu baseline Max Drawdown = −20%, sau cải tiến kỳ vọng = −20% × (1 − 25%) = **−15%**

---

## Phần 5 — Điều Kiện Để Kết Quả Hợp Lệ

**Giữ nguyên**:

| Yếu tố | Giá trị cố định |
|---|---|
| LLM model | Cùng model |
| Analysts | Cùng danh sách |
| Memory | Cùng (FIFO — chưa sửa L3) |
| Tickers & dates | Cùng nhau |
| Holding period | 5 ngày |

**Chỉ thay đổi duy nhất**: Logic điều khiển số vòng tranh luận trong `conditional_logic.py` và `default_config.py`.

---

## Phần 6 — Cách Đọc Kết Quả

Sau khi chạy xong, cần đối chiếu 2 bảng:

**Bảng 1 — Hiệu suất tài chính**
```
| Ticker | Metric       | v1 Baseline | Sau L4 | Delta |
|--------|--------------|-------------|--------|-------|
| AAPL   | Sharpe Ratio | X.XX        | X.XX   | +X.XX |
| AAPL   | Max Drawdown | -XX%        | -XX%   | -XX%  |
| BTC    | Sharpe Ratio | X.XX        | X.XX   | +X.XX |
| BTC    | Max Drawdown | -XX%        | -XX%   | -XX%  |
```

**Bảng 2 — Hiệu quả vận hành**
```
| Ticker | Avg Rounds | Avg API Calls | Avg Latency(s) |
|--------|------------|---------------|----------------|
| AAPL   | v1: 2.0    | v1: XX        | v1: XX         |
|        | L4: X.X    | L4: XX        | L4: XX         |
| BTC    | v1: 2.0    | v1: XX        | v1: XX         |
|        | L4: X.X    | L4: XX        | L4: XX         |
```
