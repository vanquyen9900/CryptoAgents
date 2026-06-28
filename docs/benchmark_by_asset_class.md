# Xác Định Metrics & Benchmark Theo Asset Class

---

## 1. Phân Loại Limitations Theo Asset Class Bị Ảnh Hưởng

| Limitation | Stock | Crypto | Lý do |
|---|:---:|:---:|---|
| **L3** — Memory System FIFO | ✅ | ✅ | Memory dùng chung cho cả hai, logic FIFO không phân biệt asset |
| **L4** — Debate Cố Định 1 Round | ✅ | ✅ | `conditional_logic.py` dùng chung cho stock và crypto |
| **L7** — Indicators Chỉ Có Standard TA | ❌ | ✅ | Stock indicators đủ dùng; crypto thiếu funding rate, OI, on-chain |
| **L8** — Backtesting Yếu | ✅ | ✅ | `_fetch_returns()` dùng chung, đều thiếu Sharpe/Drawdown tracking |

---

## 2. Baseline Paper Gốc — US Stocks (arxiv 2412.20138)

> Paper test trên **AAPL, GOOGL, AMZN, MSFT, NVDA** — năm 2024 — benchmark là **SPY**

| Metric | Buy & Hold | Single LLM | ReAct Agent | **TradingAgents (SOTA)** |
|---|---|---|---|---|
| Cumulative Return | ~12% | ~18% | ~15% | **~25–35%** |
| Sharpe Ratio | ~0.7 | ~0.9 | ~0.8 | **~1.3–1.8** |
| Max Drawdown | ~−12% | ~−15% | ~−14% | **~−8%** |
| Win Rate | N/A | ~50% | ~48% | **~55–62%** |
| Alpha vs SPY | 0% | ~+3% | ~+2% | **~+10–15%** |

---

## 3. Baseline Crypto — Cần Tự Thiết Lập (Chưa Có Trong Paper)

> CryptoAgents là bản mở rộng — **không có số liệu paper** → phải chạy thực nghiệm

### Dataset Crypto Benchmark
```
Tickers    : BTC-USD, ETH-USD, SOL-USD
Thời gian  : 2024-01-01 → 2024-12-31  (1 năm)
Tần suất   : Weekly (thứ Hai hàng tuần) → ~52 decisions/ticker
Holding    : 5 ngày (giữ nguyên như config hiện tại)
Benchmark  : BTC-USD (đã config trong benchmark_map)
```

### Baselines Crypto Cần Chạy
```
1. Buy & Hold BTC     — mua BTC từ 01/01/2024 giữ đến 31/12/2024
2. Buy & Hold ETH     — tương tự cho ETH
3. CryptoAgents v1    — code hiện tại, không cải tiến  ← BASELINE CẦN ĐO
```

---

## 4. Mapping Chi Tiết: Limitation → Asset Class → Metrics

---

### 🔴 L3 — Memory System (Ảnh Hưởng Cả Hai)

**Tại sao ảnh hưởng cả hai?**
`memory.py` → `get_past_context()` được dùng cho mọi ticker, stock hay crypto đều như nhau. Logic FIFO lấy 5 entries gần nhất không phân biệt market regime.

```
memory.py line 71-96:
  get_past_context(ticker, n_same=5, n_cross=3)
  → reversed(entries) → lấy 5 entries gần nhất
  → KHÔNG có semantic search, KHÔNG có regime filter
```

**Metric đo cho Stock (so với paper)**

| Metric | Baseline (paper SOTA) | Mục tiêu sau L3 fix |
|---|---|---|
| Win Rate | ~55–62% | > 62% |
| Cumulative Return | ~25–35% | > 35% |
| Alpha vs SPY | ~+10–15% | > +15% |

*Test tickers*: AAPL, NVDA (tickers paper dùng)
*Test period*: 2024-01-01 → 2024-06-30

**Metric đo cho Crypto (so với baseline tự đo)**

| Metric | CryptoAgents v1 (cần đo) | Mục tiêu sau L3 fix |
|---|---|---|
| Win Rate | TBD | TBD + 5–8% |
| Cumulative Return | TBD | TBD + 10–15% |
| Alpha vs BTC | TBD | TBD + 3–5% |

*Test tickers*: BTC-USD, ETH-USD
*Test period*: 2024-01-01 → 2024-06-30

**Cơ chế L3 tác động đến Win Rate:**
```
Hiện tại:
  Trade ngày 15/03 → mắc lỗi với BTC (market bearish)
  Trade ngày 22/03 → memory chỉ thấy 5 entries gần nhất
                   → KHÔNG nhớ lần 15/03 đã lỗi vì lý do gì
                   → Lặp lỗi

Sau cải tiến:
  Trade ngày 22/03 → vector search: "BTC bearish regime, similar conditions"
                   → TÌM THẤY entry 15/03 có cùng điều kiện
                   → Áp dụng lesson: "reduce exposure in bearish BTC regime"
                   → Không lặp lỗi
```

---

### 🔴 L4 — Debate Cố Định (Ảnh Hưởng Cả Hai)

**Tại sao ảnh hưởng cả hai?**
`conditional_logic.py` → `should_continue_debate()` dùng chung cho stock và crypto. Cùng 1 vòng debate cố định.

```python
# conditional_logic.py line 63–68 — DÙNG CHUNG cho mọi asset
def should_continue_debate(self, state):
    if state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds:
        return "Research Manager"   # max_debate_rounds = 1 → dừng ở count=2
```

**Metric đo cho Stock (so với paper)**

| Metric | Baseline (paper SOTA) | Mục tiêu sau L4 fix |
|---|---|---|
| Sharpe Ratio | ~1.3–1.8 | > 1.8 |
| Max Drawdown | ~−8% | < −8% |
| LLM calls/run | ~15–20 calls | −30% (early stop) |

*Test tickers*: AAPL, NVDA
*Test period*: 2024-01-01 → 2024-06-30

**Metric đo cho Crypto (so với baseline tự đo)**

| Metric | CryptoAgents v1 (cần đo) | Mục tiêu sau L4 fix |
|---|---|---|
| Sharpe Ratio | TBD | TBD + 0.2–0.4 |
| Max Drawdown | TBD | TBD − 20–30% (relative) |
| Decision Cost ($/run) | TBD | TBD × 0.7 |

*Test tickers*: BTC-USD, ETH-USD
*Test period*: 2024-01-01 → 2024-06-30

**Cơ chế L4 tác động đến Sharpe:**
```
Hiện tại:
  BTC đang pump mạnh, tất cả signals đều rõ ràng BUY
  → Bull: "rõ ràng BUY" → Bear: "vẫn muốn thêm 1 vòng nữa"
  → Debate 2 turns dù đã đồng ý → tốn token + delay

  BTC đang crash, signals mâu thuẫn
  → Bull và Bear tranh luận gay gắt
  → Dừng ở 2 turns → Research Manager không đủ thông tin
  → Quyết định kém → Max Drawdown tăng

Sau cải tiến:
  Case 1 rõ ràng: dừng sau 1 turn (early stop)
  Case 2 mâu thuẫn: tiếp tục 3–4 turns → quyết định tốt hơn
```

---

### 🟡 L7 — Standard Indicators (Chỉ Ảnh Hưởng Crypto)

**Tại sao CHỈ ảnh hưởng crypto?**

Stock indicators (SMA, EMA, MACD, RSI, Bollinger, ATR, VWMA) phù hợp với equity markets có giờ giao dịch, volume patterns bình thường.

Crypto 24/7, bị chi phối bởi:
- **Funding Rate**: Phí hoán đổi giữa long/short trong futures → chỉ số overheating
- **Open Interest**: Tổng vị thế đang mở → chỉ số leverage
- **BTC Dominance**: % market cap BTC → phát hiện altcoin season
- **Fear & Greed Index**: Tâm lý thị trường tổng thể

```python
# market_analyst.py — indicators hiện tại (tất cả là stock indicators)
"close_50_sma", "close_200_sma", "close_10_ema",   # Moving averages
"macd", "macds", "macdh",                           # MACD
"rsi",                                              # Momentum
"boll", "boll_ub", "boll_lb", "atr",               # Volatility
"vwma"                                              # Volume
# ❌ Không có: funding_rate, open_interest, btc_dominance, fear_greed
```

**Metric đo — CHỈ cho Crypto**

| Metric | CryptoAgents v1 (cần đo) | Mục tiêu sau L7 fix |
|---|---|---|
| Alpha vs BTC | TBD | TBD + 5–8% |
| Win Rate | TBD | TBD + 4–6% |
| Entry Timing Score* | TBD | TBD + 15% |

> *Entry Timing Score: % trades được vào đúng trong 2% của điểm tối ưu (local min/max trong 5 ngày)

**Ví dụ thực tế L7 sai vì thiếu crypto indicators:**
```
Ngày: 2024-03-15
RSI = 72 (overbought theo stock logic → SELL signal)
Funding Rate = +0.01% (bình thường, không overheating)
Open Interest đang tăng đều → sustained demand

Stock logic: "RSI 72 = overbought → Sell"
Crypto reality: RSI 72 + normal funding + rising OI = Bull run tiếp tục

→ Market Analyst bị mislead → đề xuất SELL sớm
→ Bỏ lỡ +20% tiếp theo trong 5 ngày
```

---

### 🟡 L8 — Backtesting Yếu (Ảnh Hưởng Cả Hai — Nhưng Khác Nhau)

**Stock**: Thiếu transaction cost (brokerage ~0.1%) và slippage (~0.05%)
**Crypto**: Thiếu transaction cost (spot ~0.1%, futures ~0.04–0.3%) và funding cost

Tác động lên số liệu:

```
Hiện tại (trading_graph.py _fetch_returns()):
  raw = (close[day5] - close[day0]) / close[day0]
  alpha = raw - benchmark_return
  # Không trừ: transaction cost, slippage, funding

Ví dụ sai số:
  Trả về raw_return = +2.0%
  Thực tế sau costs: +2.0% - 0.2%(cost) - 0.1%(slippage) = +1.7%

  Với 52 trades/năm: tích lũy sai số = 52 × 0.3% = ~15.6%/năm
  → Số liệu trên paper đẹp hơn thực tế ~15%
```

**Metric đo cho Stock**

| Metric | Hiện tại (không có cost) | Thực tế (có cost) | Delta sai số |
|---|---|---|---|
| Cumulative Return | TBD | TBD − ~10–15% | ~10–15% |
| Win Rate | TBD | TBD − 3–5% | ~3–5% |

*Transaction cost giả định*: 0.1% mỗi chiều (stock)

**Metric đo cho Crypto**

| Metric | Hiện tại (không có cost) | Thực tế (có cost) | Delta sai số |
|---|---|---|---|
| Cumulative Return | TBD | TBD − ~15–25% | ~15–25% |
| Win Rate | TBD | TBD − 5–8% | ~5–8% |

*Transaction cost giả định*: 0.1% spot + 0.05% slippage mỗi chiều (crypto)

---

## 5. Bảng Tóm Tắt — Benchmark Plan

| Limitation | Test trên Stock? | Test trên Crypto? | Stock Benchmark | Crypto Benchmark |
|---|:---:|:---:|---|---|
| **L3** Memory | ✅ AAPL, NVDA | ✅ BTC-USD, ETH-USD | So với paper SOTA | So với CryptoAgents v1 |
| **L4** Debate | ✅ AAPL, NVDA | ✅ BTC-USD, ETH-USD | So với paper SOTA | So với CryptoAgents v1 |
| **L7** Indicators | ❌ Không cần | ✅ BTC-USD, ETH-USD, SOL-USD | — | So với CryptoAgents v1 |
| **L8** Backtesting | ✅ AAPL | ✅ BTC-USD | So với paper + thực tế | So với báo cáo cũ + thực tế |

### Kỳ Vọng Tổng Hợp

**Stock (L3 + L4 + L8)**
| Metric | Paper SOTA | CryptoAgents sau cải tiến | Mục tiêu |
|---|---|---|---|
| Cumulative Return | ~25–35% | ? | **> 35%** |
| Sharpe Ratio | ~1.3–1.8 | ? | **> 1.8** |
| Max Drawdown | ~−8% | ? | **< −8%** |

**Crypto (L3 + L4 + L7 + L8)**
| Metric | CryptoAgents v1 | Sau tất cả cải tiến | Mục tiêu |
|---|---|---|---|
| Cumulative Return | TBD | TBD + ~30–40% | **> Buy & Hold BTC** |
| Sharpe Ratio | TBD | TBD + 0.4–0.6 | **> 1.2** |
| Max Drawdown | TBD | TBD − 30% (relative) | **< −20%** |
| Alpha vs BTC | TBD | TBD + 8–12% | **> +5%** |
