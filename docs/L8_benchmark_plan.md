# L8 — Backtesting Framework Yếu
## Metric · Benchmark · Kết Quả Kỳ Vọng

---

## Phần 1 — Vấn Đề Là Gì? (1 phút đọc)

Sau mỗi quyết định, hệ thống **tự đánh giá kết quả** bằng cách tính:

```python
# trading_graph.py — _fetch_returns()
raw_return = (giá_ngày_5 - giá_ngày_0) / giá_ngày_0
alpha = raw_return - return_của_benchmark
```

Chỉ vậy thôi. **Không có gì khác.**

**3 thứ quan trọng bị bỏ qua hoàn toàn:**

### ① Không có chi phí giao dịch (Transaction Cost)
Mỗi lần mua hoặc bán đều tốn phí:
- Stock: ~0.1% mỗi chiều (broker fee)
- Crypto spot: ~0.1% mỗi chiều (Binance, Bybit)

Với 52 giao dịch/năm × 0.2% (vào + ra) = **10.4% phí mỗi năm bị bỏ qua**.
→ Con số đẹp trên paper, nhưng thực tế thấp hơn ~10%.

### ② Không có Sharpe Ratio & Max Drawdown tracking
Hệ thống chỉ biết từng trade lời hay lỗ, nhưng **không tổng hợp** thành:
- Sharpe Ratio (đo lường hiệu quả risk-adjusted)
- Max Drawdown (đo mức thua lỗ tệ nhất liên tiếp)

→ Không thể so sánh được với paper gốc, không biết hệ thống đang tốt hay xấu.

### ③ Không có portfolio simulation
Mỗi trade được đánh giá **độc lập**, không có:
- Số tiền bắt đầu là bao nhiêu?
- Vào bao nhiêu % mỗi trade?
- Số dư thực sau mỗi trade?

→ Cumulative Return tính sai (cộng đơn thay vì nhân lãi kép).

---

## Phần 2 — Metric Bị Ảnh Hưởng

> ⚠️ L8 **không làm cho quyết định tốt hơn hay xấu hơn**. L8 là vấn đề **đo lường sai** — ta không biết mình đang ở đâu so với thực tế.

| Metric | Bị ảnh hưởng thế nào? |
|---|---|
| **Cumulative Return** | Bị tính **cao hơn thực tế** (thiếu phí ~10–25%/năm) |
| **Sharpe Ratio** | **Không tính được** hiện tại |
| **Max Drawdown** | **Không tính được** hiện tại |
| **Win Rate** | Không bị ảnh hưởng (đúng vì không liên quan đến phí) |

---

## Phần 3 — Kế Hoạch Benchmark

### 3.1 Áp dụng cho loại tài sản nào?

| Asset | Bị ảnh hưởng? | Mức độ sai lệch |
|---|---|---|
| **Stock** | ✅ Có | ~0.2% phí/trade × 52 trades = **~10% sai lệch/năm** |
| **Crypto** | ✅ Có | ~0.2% phí + 0.1% slippage × 52 trades = **~15–25% sai lệch/năm** |

> Crypto sai lệch nhiều hơn vì spread (bid-ask gap) rộng hơn stock, và crypto thường trade nhiều hơn.

---

### 3.2 Benchmark cho Stock

**Mục tiêu**: Đo lại toàn bộ kết quả **sau khi trừ phí** và tính đủ metrics.

| Thông số | Giá trị |
|---|---|
| Tickers test | AAPL, NVDA |
| Thời gian | 2024-01-01 → 2024-06-30 |
| Tần suất trade | Weekly |
| Holding period | 5 ngày |
| Benchmark index | SPY |
| **Transaction cost** | 0.1% mỗi chiều (vào + ra = 0.2%/trade) |
| **Slippage** | 0.05% mỗi chiều |
| **Portfolio size ban đầu** | $100,000 (giả định) |
| **Position size mỗi trade** | 20% portfolio |

**Bảng so sánh mục tiêu (Stock)**:

| Metric | Paper SOTA (không có phí) | v1 Baseline (không có phí) | Sau L8 Fix (có phí) | Mục tiêu |
|---|---|---|---|---|
| Cumulative Return | ~25–35% | Cần đo | Cần đo | **Vẫn > Buy & Hold SPY (~12%)** |
| Sharpe Ratio | ~1.3–1.8 | Không đo được | Cần đo | **> 1.0** |
| Max Drawdown | ~−8% | Không đo được | Cần đo | **< −15%** |

---

### 3.3 Benchmark cho Crypto

| Thông số | Giá trị |
|---|---|
| Tickers test | BTC-USD, ETH-USD |
| Thời gian | 2024-01-01 → 2024-06-30 |
| Tần suất trade | Weekly |
| Holding period | 5 ngày |
| Benchmark index | BTC-USD |
| **Transaction cost** | 0.1% mỗi chiều (spot) |
| **Slippage** | 0.1% mỗi chiều (crypto spread rộng hơn) |
| **Portfolio size ban đầu** | $10,000 (giả định) |
| **Position size mỗi trade** | 25% portfolio |

**Bảng so sánh mục tiêu (Crypto)**:

| Metric | Buy & Hold BTC | v1 Baseline (không có phí) | Sau L8 Fix (có phí) | Mục tiêu |
|---|---|---|---|---|
| Cumulative Return | ~150% (BTC 2024) | Cần đo (quá cao) | Cần đo (thực tế hơn) | **Vẫn > Buy & Hold BTC** |
| Sharpe Ratio | ~0.8 (BTC 2024) | Không đo được | Cần đo | **> 0.8** |
| Max Drawdown | ~−25% (BTC 2024) | Không đo được | Cần đo | **< −25%** |

---

## Phần 4 — Giải Pháp Đề Xuất

### Mục tiêu: Thêm script backtest chuẩn

Không cần thay đổi logic agent. Chỉ cần **một script riêng** để chạy simulation đúng cách.

### Công thức tính đúng

**Tính return có phí:**
```python
gross_return = (giá_cuối - giá_đầu) / giá_đầu   # return thô
cost = 0.001 + 0.001 + 0.001 + 0.001             # vào 0.1% + ra 0.1% + slippage 2 chiều
net_return = gross_return - cost                  # return thực
```

**Tính portfolio qua các trades:**
```python
portfolio = 100_000  # bắt đầu với $100k
for trade in trades:
    position = portfolio * 0.20  # vào 20% mỗi lần
    profit = position * net_return
    portfolio += profit
# cuối cùng: cumulative_return = (portfolio - 100_000) / 100_000
```

**Tính Sharpe Ratio:**
```python
import numpy as np
returns = [r1, r2, r3, ...]              # danh sách net return từng trade
sharpe = np.mean(returns) / np.std(returns) * np.sqrt(52)  # annualized weekly
```

**Tính Max Drawdown:**
```python
equity_curve = [100_000, 102_000, 101_000, 105_000, ...]   # portfolio qua thời gian
peak = max_so_far(equity_curve)
drawdown = (current - peak) / peak
max_drawdown = min(drawdown_at_each_point)
```

---

## Phần 5 — Kết Quả Kỳ Vọng

### Cơ chế "cải thiện" của L8

> L8 **không cải thiện hiệu suất**. L8 **làm con số phản ánh thực tế hơn**.

```
Trước L8 (đo sai):
  Cumulative Return = +35%  (nghe rất tốt!)
  Sharpe = ?               (không biết)
  Max Drawdown = ?         (không biết)

Sau L8 (đo đúng):
  Cumulative Return = +22%  (thực tế hơn, sau trừ ~13% phí)
  Sharpe = 1.2             (giờ mới biết được)
  Max Drawdown = -11%      (giờ mới biết được)
```

### Sai lệch kỳ vọng khi thêm phí

**Stock** (52 trades/năm × 0.2% phí):

| Metric | Trước (không phí) | Sau (có phí) | Chênh lệch |
|---|---|---|---|
| Cumulative Return | X% | X − **~10%** | ~−10% tuyệt đối |
| Win Rate | Y% | Y − **~3–5%** | ~−3–5% |

**Crypto** (52 trades/năm × 0.2% phí + 0.2% slippage):

| Metric | Trước (không phí) | Sau (có phí) | Chênh lệch |
|---|---|---|---|
| Cumulative Return | X% | X − **~20%** | ~−20% tuyệt đối |
| Win Rate | Y% | Y − **~5–8%** | ~−5–8% |

### Giá trị thực sự của L8

Sau khi sửa L8, chúng ta lần đầu tiên có thể trả lời:
1. Hệ thống có thực sự tốt hơn **Buy & Hold** sau khi trừ phí không?
2. Sharpe Ratio của chúng ta là bao nhiêu — có đạt paper SOTA (1.3–1.8) không?
3. Max Drawdown tệ nhất là bao nhiêu — có chấp nhận được không?

---

## Phần 6 — Điều Kiện Để Kết Quả Hợp Lệ

**Giữ nguyên**:

| Yếu tố | Giá trị cố định |
|---|---|
| LLM model | Cùng model |
| Analysts, Memory, Debate | Chưa sửa gì |
| Tickers & dates | Cùng nhau |
| Holding period | 5 ngày |

**Chỉ thay đổi**: Cách tính kết quả sau khi đã có danh sách quyết định — thêm phí, tính portfolio, tính Sharpe và Drawdown.

---

## Phần 7 — Files Cần Thay Đổi

| File | Việc cần làm |
|---|---|
| `scripts/run_benchmark.py` | **Tạo mới** — script chạy backtest và tính đủ metrics |
| `graph/trading_graph.py` | Cập nhật `_fetch_returns()` để trả về net return (sau phí) |
| `tradingagents/__init__.py` | Export thêm `BacktestMetrics` class |

---

## Phần 8 — Tóm Tắt

| | Stock | Crypto |
|---|---|---|
| **Có bị ảnh hưởng?** | ✅ Có | ✅ Có |
| **Sai lệch hiện tại** | ~10%/năm (thiếu phí) | ~15–25%/năm (thiếu phí + slippage) |
| **Metric chưa đo được** | Sharpe Ratio, Max Drawdown | Sharpe Ratio, Max Drawdown |
| **Giải pháp** | Script backtest đúng chuẩn | Như stock, tăng slippage |
| **Kỳ vọng** | Số liệu thực tế hơn, có thể so sánh được | Số liệu thực tế hơn |
| **Mục tiêu tối thiểu** | Return > Buy & Hold SPY sau phí | Return > Buy & Hold BTC sau phí |
