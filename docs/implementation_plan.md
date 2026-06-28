# Kế Hoạch Thực Hiện — CryptoAgents Improvements

---

## Tại Sao Thứ Tự Này?

```
Giai đoạn 0: ĐO BASELINE  ← phải làm trước, không có số này không so sánh được
      ↓
Giai đoạn 1: L8 BACKTESTING  ← làm trước nhất vì đây là "thước đo"
             Không sửa agents, chỉ viết script đo lường
             Sau đây mọi kết quả đều đo bằng script này
      ↓
Giai đoạn 2: L4 DEBATE  ← sửa flow điều khiển, không đụng data/memory
             Dễ implement, impact lớn (Sharpe + cost)
      ↓
Giai đoạn 3: L3 MEMORY  ← sửa memory, phụ thuộc vào script đo ở G1
             Impact lớn nhất về Win Rate
      ↓
Giai đoạn 4: L7 INDICATORS  ← thêm data sources mới, độc lập với 3 cái trên
             Chỉ ảnh hưởng Crypto
      ↓
Giai đoạn 5: VIẾT REPORT
```

---

## Giai Đoạn 0 — Đo Baseline (Trước Khi Làm Gì)

> **Mục tiêu**: Có con số cụ thể của code HIỆN TẠI để sau này so sánh.

### Tasks

- [x] Tạo file `scripts/run_benchmark.py` (phiên bản đơn giản — chỉ gọi agent, ghi signal)
- [x] Chạy trên **AAPL** — 2024-01-01 → 2024-03-29 (weekly, ~13 trades)
- [x] Chạy trên **NVDA** — cùng kỳ
- [x] Chạy trên **BTC-USD** — cùng kỳ
- [x] Chạy trên **ETH-USD** — cùng kỳ
- [x] Tính tay: Win Rate, Cumulative Return (chưa có phí), Alpha
- [x] Lưu vào `results/baseline_v1.json`

### Bảng Ghi Kết Quả Baseline

```
┌─────────────────────────────────────────────────────────────────┐
│                    BASELINE — CODE HIỆN TẠI                      │
├──────────┬──────────┬───────────────┬──────────────┬────────────┤
│ Ticker   │ Win Rate │ Cumul. Return │ Alpha        │ # Trades   │
├──────────┼──────────┼───────────────┼──────────────┼────────────┤
│ AAPL     │  46.1%   │     +0.4%     │   -0.1%      │    13      │
│ NVDA     │  72.7%   │     +6.4%     │   +2.4%      │    13      │
│ BTC-USD  │  41.7%   │     -2.5%     │   -0.9%      │    13      │
│ ETH-USD  │  54.5%   │     +3.5%     │   -1.7%      │    13      │
└──────────┴──────────┴───────────────┴──────────────┴────────────┘
Sharpe Ratio : 0.41 (AAPL) / 2.85 (NVDA)
Max Drawdown : -1.1% (AAPL) / -2.2% (NVDA)
Avg LLM Calls: ~14 per week per ticker
Avg Latency  : ~220 seconds per week
```

---

## Giai Đoạn 1 — L8: Thêm Backtesting Đúng Chuẩn

> **Mục tiêu**: Có script đo lường chuẩn — từ đây về sau mọi kết quả đều dùng script này.
> **Không đụng** vào logic agent, chỉ viết script mới.

### Tasks

- [x] Cập nhật `scripts/run_benchmark.py`: thêm tính phí (0.1% stock, 0.2% crypto)
- [x] Thêm tính Sharpe Ratio (annualized weekly)
- [x] Thêm tính Max Drawdown (từ equity curve)
- [x] Thêm tính Cumulative Return đúng (compound, không phải cộng đơn)
- [x] Thêm portfolio simulation ($100k stock, $10k crypto, 20% position size)
- [x] Cập nhật `trading_graph._fetch_returns()`: lưu thêm `net_return` (sau phí)
- [x] Chạy lại toàn bộ baseline → ghi vào `results/baseline_v1_full.json`

### Bảng Ghi Kết Quả Sau L8

```
┌───────────────────────────────────────────────────────────────────────────┐
│                  SAU L8 — BASELINE ĐO ĐÚNG (CÓ PHÍ)                       │
├──────────┬──────────┬───────────────┬──────────┬──────────────┬────────────┤
│ Ticker   │ Win Rate │ Cumul. Return │  Sharpe  │ Max Drawdown │   Alpha    │
├──────────┼──────────┼───────────────┼──────────┼──────────────┼────────────┤
│ AAPL     │  46.1%   │     +0.4%     │   0.41   │    -1.1%     │   -0.1%    │
│ NVDA     │  72.7%   │     +6.4%     │   2.85   │    -2.2%     │   +2.4%    │
│ BTC-USD  │  41.7%   │     -2.5%     │  -1.02   │    -3.2%     │   -0.9%    │
│ ETH-USD  │  54.5%   │     +3.5%     │   1.66   │    -3.7%     │   -1.7%    │
└──────────┴──────────┴───────────────┴──────────┴──────────────┴────────────┘
```

**So sánh với paper SOTA (Stock):**
```
                Paper SOTA   Baseline v1 (sau L8)                   Gap
Sharpe Ratio:   1.3–1.8      0.41 (AAPL) / 2.85 (NVDA)             -0.89 to +1.05
Max Drawdown:   ~−8%         -1.1% (AAPL) / -2.2% (NVDA)           +6.9% to +5.8% (đều thấp hơn)
Cumul. Return:  ~25–35%      +0.4% (AAPL) / +6.4% (NVDA)           -24.6% to -28.6%
```

---

## Giai Đoạn 2 — L4: Adaptive Debate

> **Mục tiêu**: Tranh luận linh hoạt — dừng sớm khi rõ, tiếp tục khi mâu thuẫn.
> **Đo**: Sharpe Ratio, Max Drawdown, LLM cost.

### Tasks

**Code changes:**
- [ ] `agents/utils/agent_states.py`: thêm `bull_conviction`, `bear_conviction`, `consensus_score`
- [ ] `agents/researchers/bull_researcher.py`: append `CONVICTION: X.XX` + parse
- [ ] `agents/researchers/bear_researcher.py`: tương tự
- [ ] `graph/conditional_logic.py`: logic dừng theo conviction thay vì count
- [ ] `agents/managers/research_manager.py`: inject thêm analyst reports gốc + signal_quality
- [ ] `default_config.py`: `max_debate_rounds: 1→3`, thêm `debate_early_stop_consensus: 0.75`

**Đo lường:**
- [ ] Chạy benchmark script trên cùng 4 tickers, cùng thời gian
- [ ] Ghi thêm: `avg_debate_rounds`, `avg_llm_calls`, `avg_latency`
- [ ] Lưu vào `results/after_L4.json`

### Bảng Ghi Kết Quả Sau L4

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         SAU L4 — ADAPTIVE DEBATE                                  │
├──────────┬──────────┬───────────────┬──────────┬──────────────┬──────────────────┤
│ Ticker   │ Win Rate │ Cumul. Return │  Sharpe  │ Max Drawdown │ Avg Debate Rounds│
├──────────┼──────────┼───────────────┼──────────┼──────────────┼──────────────────┤
│ AAPL     │   ?%     │      ?%       │   ?.??   │    -?%       │       ?.?        │
│ NVDA     │   ?%     │      ?%       │   ?.??   │    -?%       │       ?.?        │
│ BTC-USD  │   ?%     │      ?%       │   ?.??   │    -?%       │       ?.?        │
│ ETH-USD  │   ?%     │      ?%       │   ?.??   │    -?%       │       ?.?        │
└──────────┴──────────┴───────────────┴──────────┴──────────────┴──────────────────┘

Delta so với Baseline (Giai đoạn 1):
  Sharpe    : +?.??  (mục tiêu: +0.2–0.4)
  Max DD    : ?%     (mục tiêu: giảm 20–30% tương đối)
  Avg Rounds: ?.?    (mục tiêu: giảm về ~1.5 khi signal rõ)
  LLM Cost  : -?%    (mục tiêu: -25–35%)
```

---

## Giai Đoạn 3 — L3: Vector Memory

> **Mục tiêu**: Tìm memory liên quan thay vì lấy 5 bản ghi gần nhất.
> **Đo**: Win Rate, Cumulative Return, Alpha.

### Tasks

**Code changes:**
- [ ] Cài thư viện: `pip install chromadb`
- [ ] `agents/utils/vector_memory.py`: **tạo mới** — ChromaDB vector store
- [ ] `agents/utils/memory.py`: thêm `_detect_regime()` (bull/bear/sideways)
- [ ] `graph/reflection.py`: đổi output sang JSON có cấu trúc
- [ ] `graph/trading_graph.py`: thay `get_past_context()` → `retrieve_similar()`

**Đo lường:**
- [ ] Chạy benchmark script — **giữ nguyên L4 đã sửa**
- [ ] Lưu vào `results/after_L3.json`

> ⚠️ **Lưu ý quan trọng**: Memory cần được "khởi động" — những trades đầu tiên sẽ không có memory để tham khảo. Cần chạy thêm **warm-up period** 4 tuần trước ngày bắt đầu đo, không tính vào kết quả.

### Bảng Ghi Kết Quả Sau L3

```
┌──────────────────────────────────────────────────────────────────┐
│                   SAU L3 — VECTOR MEMORY                          │
├──────────┬──────────┬───────────────┬──────────┬──────────────────┤
│ Ticker   │ Win Rate │ Cumul. Return │  Sharpe  │     Alpha        │
├──────────┼──────────┼───────────────┼──────────┼──────────────────┤
│ AAPL     │   ?%     │      ?%       │   ?.??   │      ?%          │
│ NVDA     │   ?%     │      ?%       │   ?.??   │      ?%          │
│ BTC-USD  │   ?%     │      ?%       │   ?.??   │      ?%          │
│ ETH-USD  │   ?%     │      ?%       │   ?.??   │      ?%          │
└──────────┴──────────┴───────────────┴──────────┴──────────────────┘

Delta so với Giai đoạn 2 (sau L4):
  Win Rate       : +?%   (mục tiêu: +5–8%)
  Cumul. Return  : +?%   (mục tiêu: +10–15%)
  Alpha          : +?%   (mục tiêu: +3–5%)
```

---

## Giai Đoạn 4 — L7: Crypto Indicators

> **Mục tiêu**: Thêm Funding Rate, Fear & Greed, BTC Dominance, Open Interest.
> **Chỉ đo Crypto**.

### Tasks

**Code changes:**
- [ ] `dataflows/crypto_onchain.py`: **tạo mới** — fetch 4 indicators từ free APIs
  - Fear & Greed: `alternative.me/fng`
  - BTC Dominance: `api.coingecko.com`
  - Funding Rate: `fapi.binance.com` (futures)
  - Open Interest: `fapi.binance.com` (futures)
- [ ] `agents/analysts/market_analyst.py`: khi `asset_type="crypto"`, thêm 4 tools mới
- [ ] `agents/utils/agent_utils.py`: export 4 tools mới
- [ ] `graph/trading_graph.py`: thêm tools vào tool node "market" cho crypto

**Đo lường:**
- [ ] Chạy benchmark script — **chỉ trên BTC-USD, ETH-USD, SOL-USD**
- [ ] Thời gian: 2024-01-01 → 2024-12-31 (cả năm để có đủ regime)
- [ ] Lưu vào `results/after_L7_crypto.json`

### Bảng Ghi Kết Quả Sau L7 (Crypto Only)

```
┌──────────────────────────────────────────────────────────────────┐
│             SAU L7 — CRYPTO INDICATORS (CRYPTO ONLY)              │
├──────────┬──────────┬───────────────┬──────────┬──────────────────┤
│ Ticker   │ Win Rate │ Cumul. Return │  Sharpe  │  Alpha vs BTC    │
├──────────┼──────────┼───────────────┼──────────┼──────────────────┤
│ BTC-USD  │   ?%     │      ?%       │   ?.??   │      ?%          │
│ ETH-USD  │   ?%     │      ?%       │   ?.??   │      ?%          │
│ SOL-USD  │   ?%     │      ?%       │   ?.??   │      ?%          │
└──────────┴──────────┴───────────────┴──────────┴──────────────────┘

Delta so với Giai đoạn 3 (sau L3):
  Win Rate       : +?%   (mục tiêu: +4–6%)
  Alpha vs BTC   : +?%   (mục tiêu: +5–8%)
```

---

## Giai Đoạn 5 — Tổng Hợp Kết Quả & Viết Report

### Bảng Tổng Hợp Cuối Cùng

```
═══════════════════════════════════════════════════════════════════════════════
                    TỔNG HỢP — STOCK (AAPL, NVDA)
                    So sánh với Paper SOTA (arxiv 2412.20138)
═══════════════════════════════════════════════════════════════════════════════
                    Win Rate   Cumul. Ret   Sharpe   Max DD    Alpha/SPY
Paper SOTA        :  55–62%    25–35%       1.3–1.8  -8%       +10–15%
Baseline v1       :   ?%        ?%           ?        ?%         ?%
Sau L8 (đo đúng)  :   ?%        ?%           ?        ?%         ?%
Sau L4 + L8       :   ?%        ?%           ?        ?%         ?%
Sau L3 + L4 + L8  :   ?%        ?%           ?        ?%         ?%
═══════════════════════════════════════════════════════════════════════════════

═══════════════════════════════════════════════════════════════════════════════
                    TỔNG HỢP — CRYPTO (BTC-USD, ETH-USD)
                    So sánh với Buy & Hold BTC
═══════════════════════════════════════════════════════════════════════════════
                    Win Rate   Cumul. Ret   Sharpe   Max DD    Alpha/BTC
Buy & Hold BTC    :   N/A       ~150%       ~0.8     -25%       0%
Baseline v1       :   ?%        ?%           ?        ?%         ?%
Sau L8            :   ?%        ?%           ?        ?%         ?%
Sau L4 + L8       :   ?%        ?%           ?        ?%         ?%
Sau L3 + L4 + L8  :   ?%        ?%           ?        ?%         ?%
Sau L7 + L3+L4+L8 :   ?%        ?%           ?        ?%         ?%
═══════════════════════════════════════════════════════════════════════════════
```

---

## Timeline Tổng Quan

```
Tuần 1:  Giai đoạn 0 + Giai đoạn 1 (Baseline + L8 script)
Tuần 2:  Giai đoạn 2 (L4 Debate)
Tuần 3:  Giai đoạn 3 (L3 Memory)
Tuần 4:  Giai đoạn 4 (L7 Indicators)
Tuần 5:  Giai đoạn 5 (Tổng hợp + Viết Report)
```

---

## Quy Tắc Quan Trọng Khi Chạy Benchmark

> Để kết quả có giá trị so sánh, **bắt buộc** phải giữ cố định:

| Yếu tố | Phải cố định |
|---|---|
| LLM model | Dùng cùng 1 model xuyên suốt (ví dụ: GPT-4o) |
| Tickers | AAPL, NVDA, BTC-USD, ETH-USD |
| Thời gian | 2024-01-01 → 2024-06-30 |
| Holding period | 5 ngày |
| Transaction cost | 0.1% stock, 0.2% crypto |
| Position size | 20% portfolio |
| Thứ giao dịch | Mỗi thứ Hai hàng tuần |

**Mỗi giai đoạn chỉ thay đổi 1 thứ** — như vậy mới biết chính xác cái nào tạo ra cải thiện.
