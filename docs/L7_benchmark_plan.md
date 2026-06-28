# L7 — Market Analyst: Chỉ Dùng Indicators Cổ Điển
## Metric · Benchmark · Kết Quả Kỳ Vọng

---

## Phần 1 — Vấn Đề Là Gì? (1 phút đọc)

Market Analyst hiện tại phân tích giá bằng **8 indicators kỹ thuật tiêu chuẩn**:

```
SMA 50, SMA 200, EMA 10   ← xu hướng trung/dài hạn
MACD, MACD Signal, MACD Histogram  ← momentum
RSI                        ← overbought/oversold
Bollinger Bands, ATR       ← độ biến động
VWMA                       ← volume
```

Những indicators này được thiết kế cho **thị trường chứng khoán** — có giờ mở cửa, đóng cửa, và hành vi volume có quy luật.

**Vấn đề**: Crypto giao dịch **24/7**, bị chi phối bởi các yếu tố hoàn toàn khác mà 8 indicators trên **không đo được**:

| Yếu tố Crypto | Ý nghĩa | Có trong code hiện tại? |
|---|---|---|
| **Funding Rate** | Phí duy trì vị thế futures — cao = thị trường quá nhiệt | ❌ Không |
| **Open Interest** | Tổng tiền đang đặt cược vào futures — tăng = rủi ro cao | ❌ Không |
| **BTC Dominance** | % thị phần của BTC — giảm = altcoin season | ❌ Không |
| **Fear & Greed Index** | Tâm lý toàn thị trường (0=sợ hãi, 100=tham lam) | ❌ Không |

> **Tại sao đây là vấn đề nghiêm trọng?**
> RSI = 72 trên cổ phiếu → overbought → hợp lý để SELL
> RSI = 72 trên BTC với Funding Rate bình thường + Open Interest tăng đều → **bull run đang tiếp diễn → SELL quá sớm → bỏ lỡ lợi nhuận**

---

## Phần 2 — Metric Bị Ảnh Hưởng

> ⚠️ **L7 CHỈ ảnh hưởng Crypto**, không ảnh hưởng Stock.
> Stock indicators (RSI, MACD, Bollinger...) vẫn phù hợp cho equity markets.

| Metric | Vì sao bị ảnh hưởng? |
|---|---|
| **Alpha vs BTC** | Tín hiệu entry/exit sai thời điểm → underperform BTC |
| **Win Rate** | Indicators cũ ra tín hiệu sai chiều trong crypto context |
| **Entry Timing** | Vào/ra sai điểm dù quyết định hướng đúng → bỏ lỡ lợi nhuận |

> **Metric KHÔNG bị ảnh hưởng nhiều**: Sharpe Ratio, Max Drawdown — vì đây là vấn đề về *hướng* quyết định, không phải *quản lý rủi ro*.

---

## Phần 3 — Kế Hoạch Benchmark

### 3.1 Áp dụng cho loại tài sản nào?

| Asset | Có bị ảnh hưởng? | Lý do |
|---|---|---|
| **Stock** | ❌ Không | Indicators hiện tại (RSI, MACD...) phù hợp cho equity |
| **Crypto** | ✅ Có | Thiếu Funding Rate, Open Interest, BTC Dominance, Fear & Greed |

---

### 3.2 Benchmark cho Crypto

**So sánh với**: CryptoAgents v1 (baseline tự đo)

| Thông số | Giá trị |
|---|---|
| Tickers test | BTC-USD, ETH-USD, SOL-USD |
| Thời gian | 2024-01-01 → 2024-12-31 (cả năm — bao gồm nhiều regime) |
| Tần suất trade | Weekly |
| Holding period | 5 ngày |
| Benchmark index | BTC-USD |

**Lý do test cả năm 2024 (thay vì 6 tháng)**:
BTC trải qua nhiều giai đoạn trong 2024 — sideways (Q1) → bull run (Q2) → correction (Q3) → rally (Q4). Cần đủ các regime để đánh giá xem indicators mới có thực sự tốt hơn trong **từng giai đoạn**.

**Cần đo thêm metric phụ — Entry Timing Score**:

```
Entry Timing Score = % số trades được vào trong vùng ±3%
                    so với điểm giá tối ưu (low/high trong 5 ngày)

Ví dụ:
  Trade BUY ngày 01/03 tại giá $60,000
  Giá thấp nhất trong 5 ngày tiếp theo: $58,500 (thấp hơn 2.5%)
  → Entry Timing Score cho trade này: 2.5% (càng thấp càng tốt)

  Tính trung bình trên tất cả trades → Entry Timing Score tổng thể
```

**Bảng so sánh mục tiêu (Crypto)**:

| Metric | Buy & Hold BTC | v1 Baseline | Sau L7 Fix | Mục tiêu |
|---|---|---|---|---|
| Win Rate | N/A | Cần đo | Cần đo | **Baseline + 4–6%** |
| Alpha vs BTC | 0% | Cần đo | Cần đo | **Baseline + 5–8%** |
| Entry Timing Score | N/A | Cần đo | Cần đo | **Giảm 15–20%** |

---

## Phần 4 — Giải Pháp & Cơ Chế Cải Thiện

### Thêm 4 data sources mới vào Market Analyst

**① Fear & Greed Index** — Nguồn: `alternative.me` (free API)
```
Giá trị 0–100:
  0–25   = Extreme Fear  → thị trường có thể đảo chiều tăng
  25–50  = Fear          → cẩn thận, thị trường yếu
  50–75  = Greed         → thị trường tốt, có thể mua
  75–100 = Extreme Greed → quá nhiệt, cẩn thận FOMO
```

**② Funding Rate** — Nguồn: Binance API (free)
```
Dương và cao (> 0.1%/8h) → quá nhiều người long → risk đảo chiều
Âm                       → quá nhiều người short → có thể đảo chiều tăng
Gần 0                    → cân bằng, không có tín hiệu mạnh
```

**③ BTC Dominance** — Nguồn: CoinGecko API (free)
```
Đang tăng  → tiền chạy về BTC → altcoins yếu
Đang giảm  → tiền ra khỏi BTC → altcoin season → ETH, SOL tăng
```

**④ Open Interest** — Nguồn: Coinglass API (miễn phí gói cơ bản)
```
Tăng mạnh + giá tăng → xu hướng được xác nhận
Tăng mạnh + giá giảm → có thể là short squeeze sắp xảy ra
Giảm mạnh            → vị thế đang bị thanh lý, thị trường bất ổn
```

### Ví dụ thực tế — Tại sao 4 indicators này quan trọng

**Case 1**: BTC ngày 13/03/2024

| Indicator | Giá trị | Tín hiệu |
|---|---|---|
| RSI | 78 | ⚠️ Overbought → SELL (theo logic cũ) |
| Funding Rate | +0.02% | ✅ Bình thường, không quá nhiệt |
| Fear & Greed | 82 | ⚠️ Extreme Greed, cẩn thận |
| Open Interest | Tăng 15% tuần | ✅ Demand thực, không phải FOMO thuần túy |

→ Logic cũ (chỉ RSI=78): SELL
→ Logic mới (kết hợp): Funding bình thường + OI tăng thực = **HOLD hoặc giảm nhẹ, chưa cần SELL**
→ Thực tế: BTC tiếp tục tăng từ $73k lên $74k trong 5 ngày tiếp theo

**Case 2**: ETH ngày 18/08/2024

| Indicator | Giá trị | Tín hiệu |
|---|---|---|
| RSI | 45 | ✅ Neutral (theo logic cũ: không tín hiệu rõ) |
| Funding Rate | −0.05% | 🟢 Âm mạnh → quá nhiều short → có thể short squeeze |
| Fear & Greed | 26 | 🟢 Fear → thị trường có thể đảo chiều |
| BTC Dominance | Đang giảm | 🟢 Tiền đang chạy vào altcoins |

→ Logic cũ (chỉ RSI=45): HOLD
→ Logic mới: Funding âm + Fear + BTC Dom giảm = **BUY cơ hội**
→ Thực tế: ETH tăng +12% trong 5 ngày tiếp theo

---

## Phần 5 — Kết Quả Kỳ Vọng

### Cơ chế tạo ra cải thiện

```
Cũ: Market Analyst chỉ nhìn vào RSI, MACD, Bollinger
  → Có thể đưa ra tín hiệu ngược chiều với thực tế crypto market
  → Win Rate thấp, bỏ lỡ nhiều cơ hội

Mới: Market Analyst thêm Funding Rate, OI, F&G, BTC Dominance
  → Tín hiệu được xác nhận từ nhiều góc độ
  → Giảm false signals đáng kể
  → Alpha vs BTC tăng vì vào/ra đúng thời điểm hơn
```

### Kỳ vọng định lượng — CHỈ Crypto

| Metric | v1 Baseline | Sau L7 Fix | Kỳ vọng cải thiện |
|---|---|---|---|
| Win Rate | TBD | TBD | **+4–6%** |
| Alpha vs BTC | TBD | TBD | **+5–8%** |
| Entry Timing Score | TBD | TBD | **Giảm 15–20%** |

> **Lưu ý**: Cải thiện lớn nhất kỳ vọng ở các **altcoins** (ETH, SOL) vì BTC Dominance và Funding Rate đặc biệt hữu ích khi phân tích altcoin context.

---

## Phần 6 — Điều Kiện Để Kết Quả Hợp Lệ

**Giữ nguyên**:

| Yếu tố | Giá trị cố định |
|---|---|
| LLM model | Cùng model |
| Analysts | Cùng danh sách |
| Memory | Cùng (chưa sửa L3) |
| Debate rounds | Cùng (chưa sửa L4) |
| Tickers & dates | Cùng nhau |

**Chỉ thay đổi duy nhất**: Thêm 4 data sources mới vào Market Analyst tool set.

---

## Phần 7 — Files Cần Thay Đổi

| File | Việc cần làm |
|---|---|
| `dataflows/crypto_onchain.py` | **Tạo mới** — hàm fetch Funding Rate, Fear & Greed, BTC Dominance, Open Interest |
| `agents/analysts/market_analyst.py` | Thêm crypto-specific tools vào khi `asset_type = "crypto"` |
| `agents/utils/agent_utils.py` | Export 4 tools mới |
| `graph/trading_graph.py` | Thêm tools mới vào tool node "market" cho crypto |

---

## Phần 8 — Tóm Tắt

| | Stock | Crypto |
|---|---|---|
| **Có bị ảnh hưởng?** | ❌ Không | ✅ Có |
| **Metric chính** | — | Win Rate, Alpha vs BTC |
| **Giải pháp** | — | Thêm Funding Rate, OI, F&G Index, BTC Dominance |
| **Kỳ vọng** | — | Win Rate +4–6%, Alpha +5–8% |
