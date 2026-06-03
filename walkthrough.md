# CryptoAgents — Tài liệu Thuyết trình: Data Layer

---

## 1. Giới thiệu

**CryptoAgents** là hệ thống phân tích đầu tư đa tác nhân LLM chuyên biệt cho thị trường tiền mã hóa. Tài liệu này trình bày toàn bộ **tầng dữ liệu (Data Layer)** — cách hệ thống thu thập, làm sạch, xử lý và mô hình hóa dữ liệu để cung cấp cho các Agent.

---

## 2. Kiến trúc Tổng thể Data Layer

```
┌─────────────────────────────────────────────────────────────────────┐
│                       CRYPTOAGENTS DATA LAYER                        │
│                                                                      │
│   Nguồn dữ liệu            Xử lý trung tâm         Output cho Agent │
│   ─────────────            ────────────────         ─────────────── │
│                                                                      │
│   Yahoo Finance  ──►   interface.py (Router)  ──►  OHLCV Data        │
│                         │                          Technical Signals  │
│   Alpha Vantage  ──►    ├──► stockstats_utils.py   News & Sentiment  │
│                         │    (OHLCV + Indicators)  Anomaly Report    │
│   Yahoo News    ──►     ├──► y_finance.py           Trend Forecast   │
│                         │    (Price + News)                          │
│   StockTwits    ──►     │                                            │
│                         └──► quantitative_models.py                  │
│   Reddit        ──►          (TensorFlow Pipeline)                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Nguồn Dữ liệu

### 3.1 Yahoo Finance (yfinance) — Nguồn chính

**Dữ liệu cung cấp:**
- OHLCV hàng ngày — 5 năm lịch sử
- Tin tức theo ticker
- Tin tức vĩ mô / global headlines

**Cơ chế tải dữ liệu:**
```python
data = yf.download(
    symbol,
    start=start_str,    # 5 năm trước curr_date
    end=end_str,
    auto_adjust=True,   # tự điều chỉnh giá cho split/dividend
    progress=False,
)
```

**Caching thông minh:** Dữ liệu OHLCV được cache thành file CSV tại `~/.tradingagents/cache/`. Lần gọi tiếp theo đọc từ cache — giảm latency và tránh rate limit.

**Retry với Exponential Backoff:**
```python
def yf_retry(func, max_retries=3, base_delay=2.0):
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            delay = base_delay * (2 ** attempt)  # 2s → 4s → 8s
            time.sleep(delay)
```

### 3.2 Alpha Vantage — Nguồn dự phòng

Hỗ trợ như vendor thứ hai cho OHLCV, chỉ báo kỹ thuật và tin tức. Khi Alpha Vantage bị rate limit (HTTP 429), `interface.py` tự động chuyển sang Yahoo Finance.

### 3.3 Dữ liệu Cảm xúc Thị trường

| Nguồn | Loại dữ liệu | Agent sử dụng |
|---|---|---|
| Yahoo News | Tin tức tài chính theo ticker | News Analyst |
| Global News | Tin tức vĩ mô, Fed, lãi suất | News Analyst |
| StockTwits | Bình luận cộng đồng nhà đầu tư | Sentiment Analyst |
| Reddit | Thảo luận diễn đàn đầu tư | Sentiment Analyst |

---

## 4. Đặc điểm Dữ liệu Tiền mã hóa

Khác với thị trường chứng khoán truyền thống (Thứ 2–6, giờ hành chính), thị trường crypto có các đặc điểm riêng:

- **Giao dịch 24/7** — không có ngày nghỉ, không có giờ đóng cửa
- **Biến động cao** — giá có thể thay đổi 10–30% trong một ngày
- **Sự kiện bất thường thường xuyên** — flash crash, liquidation cascade, pump-and-dump, whale movement
- **Khối lượng giao dịch bất ổn** — thay đổi mạnh theo tin tức và tâm lý thị trường
- **Không có báo cáo tài chính doanh nghiệp** — không có P/E, EPS, balance sheet

Do đó hệ thống phải xử lý dữ liệu liên tục, phát hiện bất thường và dự báo xu hướng thay vì phân tích cơ bản truyền thống.

---

## 5. Cấu trúc Dữ liệu OHLCV

Đây là dữ liệu giá cơ bản — đầu vào cho tất cả các pipeline xử lý.

| Thuộc tính | Ý nghĩa |
|---|---|
| `Date` | Ngày giao dịch (YYYY-MM-DD) |
| `Open` | Giá mở cửa |
| `High` | Giá cao nhất trong ngày |
| `Low` | Giá thấp nhất trong ngày |
| `Close` | Giá đóng cửa |
| `Volume` | Khối lượng giao dịch |

**Ví dụ dữ liệu BTC-USD:**

| Date | Open | High | Low | Close | Volume |
|---|---|---|---|---|---|
| 2026-05-25 | 105,000 | 108,000 | 104,000 | 107,000 | 4.2B |
| 2026-05-26 | 107,000 | 109,000 | 106,000 | 108,500 | 4.5B |
| 2026-05-27 | 108,500 | 110,000 | 107,000 | 109,200 | 3.8B |

**Quy mô dữ liệu:** 365 ngày/năm × 5 năm = **~1.825 bản ghi** cho mỗi tài sản.

---

## 6. Chất lượng Dữ liệu — `stockstats_utils.py`

### 6.1 Chuẩn hóa DataFrame

```python
def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    # Chuẩn hóa tên cột Date (xử lý 'index', 'Datetime', 'date')
    if "Date" not in data.columns:
        for candidate in ("index", "Datetime", "date"):
            if candidate in data.columns:
                data = data.rename(columns={candidate: "Date"})
                break

    # Parse ngày tháng về chuẩn thống nhất
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    # Forward-fill + Backward-fill để bù dữ liệu thiếu
    data[price_cols] = data[price_cols].ffill().bfill()
    return data
```

### 6.2 Kiểm soát Look-ahead Bias

Khi agent phân tích tại ngày `curr_date`, hệ thống đảm bảo tuyệt đối không có dữ liệu tương lai lọt vào:

```python
def load_ohlcv(symbol, curr_date):
    # ...tải/cache dữ liệu...
    # Filter: chỉ giữ dữ liệu ≤ curr_date
    data = data[data["Date"] <= curr_date_dt]
    return data
```

### 6.3 Hỗ trợ Giao dịch 24/7 — Preceding Day Fallback

Khi agent hỏi dữ liệu một ngày cụ thể mà không có trong dataset (lệch múi giờ, API gap), hệ thống tự động điền giá trị ngày gần nhất trước đó — thay vì trả về lỗi:

```python
# Trong stockstats_utils.py
preceding_rows = df[df["Date_dt"] <= curr_date_dt]
if not preceding_rows.empty:
    return preceding_rows.iloc[-1][indicator]  # ← giá trị ngày gần nhất

# Trong y_finance.py (cửa sổ trượt)
preceding_dates = [d for d in indicator_data.keys() if d < date_str]
if preceding_dates:
    preceding_dates.sort()
    indicator_value = indicator_data[preceding_dates[-1]]
```

---

## 7. Chỉ báo Kỹ thuật — Technical Indicators

Hệ thống hỗ trợ tính toán 12 chỉ báo kỹ thuật từ dữ liệu OHLCV thô:

| Nhóm | Chỉ báo | Ý nghĩa |
|---|---|---|
| Moving Averages | `close_50_sma` | Trung bình động 50 ngày — xu hướng trung hạn |
| Moving Averages | `close_200_sma` | Trung bình động 200 ngày — xu hướng dài hạn |
| Moving Averages | `close_10_ema` | EMA 10 ngày — phản ứng nhanh với thị trường |
| MACD | `macd` | Giao động 2 EMA — xác nhận xu hướng |
| MACD | `macds` | Đường tín hiệu của MACD |
| MACD | `macdh` | Histogram MACD — đo sức mạnh momentum |
| Momentum | `rsi` | Chỉ số sức mạnh tương đối — overbought/oversold |
| Volatility | `boll` | Bollinger Band trung tâm (SMA 20) |
| Volatility | `boll_ub` | Bollinger Band trên — vùng overbought |
| Volatility | `boll_lb` | Bollinger Band dưới — vùng oversold |
| Volatility | `atr` | Average True Range — đo mức độ biến động |
| Volume | `vwma` | Volume-Weighted Moving Average |

---

## 8. Nhận diện Ticker Crypto — `y_finance.py`

Hệ thống tự động phân biệt ticker crypto với cổ phiếu thông qua hàm:

```python
def is_crypto_symbol(symbol: str) -> bool:
    normalized = symbol.strip().upper()
    return normalized.endswith(("-USD", "-USDT", "-USDC", "-BTC", "-ETH"))
```

**Các ticker được nhận diện là Crypto:**

| Suffix | Ví dụ | Benchmark tự động |
|---|---|---|
| `-USD` | `BTC-USD`, `ETH-USD`, `SOL-USD` | `BTC-USD` |
| `-USDT` | `BTC-USDT`, `BNB-USDT` | `BTC-USD` |
| `-USDC` | `ETH-USDC` | `BTC-USD` |
| `-BTC` | `ETH-BTC`, `SOL-BTC` | `BTC-USD` |
| `-ETH` | `UNI-ETH`, `LINK-ETH` | `BTC-USD` |

Khi ticker là crypto, hệ thống **chặn hoàn toàn** các yêu cầu dữ liệu doanh nghiệp và trả về thông báo rõ ràng:
> *"Corporate fundamental metrics are not applicable for the cryptocurrency BTC-USD. Please refer to quantitative indicators, market dynamics, and sentiment reports."*

---

## 9. Định tuyến Dữ liệu — `interface.py`

Router trung tâm điều phối mọi yêu cầu dữ liệu từ Agent đến đúng nguồn:

```python
def route_to_vendor(method: str, *args, **kwargs):
    category = get_category_for_method(method)   # xác định nhóm
    vendor   = get_vendor(category, method)       # yfinance / alpha_vantage
    impl     = VENDOR_METHODS[method][vendor]     # hàm cụ thể
    try:
        return impl(*args, **kwargs)
    except AlphaVantageRateLimitError:
        # Tự động chuyển sang vendor tiếp theo
        continue
```

**4 nhóm dữ liệu được quản lý:**

| Category | Tools | Nguồn dữ liệu |
|---|---|---|
| `core_stock_apis` | `get_stock_data` | OHLCV thô từ yfinance/Alpha Vantage |
| `technical_indicators` | `get_indicators` | Tính từ OHLCV qua stockstats |
| `news_data` | `get_news`, `get_global_news` | Yahoo News, Alpha Vantage News |
| `quantitative_analysis` | `get_anomaly_signals`, `get_trend_predictions` | TensorFlow pipeline (local) |

---

## 10. Feature Engineering — `quantitative_models.py`

Dữ liệu OHLCV thô được biến đổi thành 4 đặc trưng có ý nghĩa thống kê trước khi đưa vào mô hình học sâu.

### 10.1 Các Đặc trưng Được Tính

| Đặc trưng | Công thức | Ý nghĩa |
|---|---|---|
| `log_ret` | $\ln(C_t / C_{t-1})$ | Tỷ suất sinh lời log — chuẩn hóa biến động |
| `hl_vol` | $(H_t - L_t) / C_t$ | Biên độ giá trong ngày — đo rủi ro ngắn hạn |
| `vol_ratio` | $V_t / \text{SMA}(V, 10)$ | Đà khối lượng — phát hiện dòng tiền bất thường |
| `ret_std` | $\text{std}(\text{log\_ret},\ 5)$ | Biến động rolling 5 ngày — ổn định thị trường |

### 10.2 Chuẩn hóa Min-Max

Tất cả đặc trưng được scale về khoảng `[0.0, 1.0]`:

```python
def scale_features(features_df: pd.DataFrame) -> np.ndarray:
    cols = ['log_ret', 'hl_vol', 'vol_ratio', 'ret_std']
    data = features_df[cols].values
    min_vals = np.min(data, axis=0)
    max_vals = np.max(data, axis=0)
    range_vals = np.where(max_vals - min_vals == 0, 1e-8, max_vals - min_vals)
    return (data - min_vals) / range_vals
```

### 10.3 Tạo Chuỗi Thời gian (Rolling Window)

```python
def prepare_sequences(data: np.ndarray, window_size: int = 10):
    X = []
    for i in range(len(data) - window_size + 1):
        X.append(data[i:i + window_size])
    return np.array(X)
```

```
Dữ liệu 2D: (N ngày,  4 đặc trưng)
      ↓  Rolling Window 10 ngày
Tensor 3D: (N−9 samples,  10 timesteps,  4 features)
```

---

## 11. Mô hình Học sâu — TensorFlow

### 11.1 Mô hình 1: Phát hiện Bất thường (Autoencoder)

**Mục tiêu:** Phát hiện flash crash, pump-and-dump, liquidation cascade, whale movement.

**Kiến trúc mạng:**
```
Input  (batch, 10, 4)
  → Flatten       (40)
  → Dense(8, ReLU)          ← Encoder lớp 1
  → Dense(4, ReLU)          ← Bottleneck (nén thông tin)
  → Dense(8, ReLU)          ← Decoder lớp 1
  → Dense(40, Sigmoid)      ← Decoder lớp 2
  → Reshape (batch, 10, 4)  ← Output
```

**Nguyên lý hoạt động:**

Model được huấn luyện để **tái tạo (reconstruct)** các chuỗi giá bình thường. Khi gặp hành vi bất thường, lỗi tái tạo (MSE) tăng vọt:

```python
# Huấn luyện trên 180 ngày lịch sử
model.fit(X, X, epochs=10, batch_size=16)

# Tính reconstruction error cho mọi sequence
reconstructed = model.predict(X)
mse = np.mean(np.square(X - reconstructed), axis=(1, 2))

# Ngưỡng động: percentile 95% của lịch sử MSE
threshold = np.percentile(mse, 95)

# Kết luận: sequence mới nhất có vượt ngưỡng không?
is_anomaly = bool(mse[-1] > threshold)
```

**Output:**
```
| Metric                     | Value                                    |
| Market State               | **ANOMALY DETECTED**                     |
| Reconstruction MSE         | 0.042816                                 |
| Anomaly Threshold (P95)    | 0.031450                                 |
| Total Historical Anomalies | 9 occurrences                            |
| Recent Anomaly Dates       | 2026-05-15, 2026-05-22, 2026-05-28       |
```

**Fallback:** Nếu TF model thất bại → phát hiện bằng `|return| > 2σ`.

---

### 11.2 Mô hình 2: Dự báo Xu hướng Giá (LSTM)

**Mục tiêu:** Dự báo hướng đi giá trong 3 phiên tới — UP / HOLD / DOWN.

**Kiến trúc mạng:**
```
Input  (batch, 10, 4)
  → LSTM(16 units)       ← Ghi nhớ quan hệ chuỗi thời gian
  → Dropout(0.2)         ← Chống overfitting
  → Dense(3, Softmax)    ← [P_DOWN, P_HOLD, P_UP]
```

**Chiến lược gán nhãn:**

```python
# Tỷ suất sinh lời 3 ngày tới
df_train['future_ret'] = df_train['Close'].shift(-3) / df_train['Close'] - 1.0

# Quy tắc phân loại
future_ret < -0.02  →  Label 0: DOWN  🔴  (giảm > 2%)
future_ret > +0.02  →  Label 2: UP    🟢  (tăng > 2%)
Còn lại             →  Label 1: HOLD  🟡  (dao động ±2%)
```

**Quá trình huấn luyện:**
```python
# Loại 3 sequence cuối (nhãn tương lai chưa khả dụng)
X_train = X[:-3]
y_train = labels[window_size - 1:-3]

model.fit(X_train, y_train, epochs=10, batch_size=16)

# Dự báo trên sequence mới nhất (hôm nay)
probs = model.predict(X[-1:])
pred_label = int(np.argmax(probs))   # 0=DOWN, 1=HOLD, 2=UP
```

**Output:**
```
| Parameter             | Value    |
| Forecasted Direction  | **UP**   |
| Confidence Level      | 72.3%    |
| Probability: UP       | 72.3%    |
| Probability: HOLD     | 21.1%    |
| Probability: DOWN     | 6.6%     |
```

**Fallback:** Nếu LSTM thất bại → dùng SMA-10 / SMA-20 crossover (confidence 65%).

---

## 12. Tóm tắt Pipeline Dữ liệu Hoàn chỉnh

```
Yahoo Finance / Alpha Vantage
        │
        ▼  (yf.download + cache CSV)
  Raw OHLCV DataFrame
  5 năm lịch sử, ~1825 rows
        │
        ├──── Filter ≤ curr_date         (chống look-ahead bias)
        │
        ├──── _clean_dataframe()
        │     • Chuẩn hóa tên cột Date
        │     • Parse timestamp
        │     • ffill / bfill NaN
        │
        ├──► [Path A] Technical Indicators
        │    stockstats → RSI, MACD, Bollinger, ATR, VWMA,...
        │    24/7 fallback: điền giá trị ngày gần nhất
        │
        └──► [Path B] TensorFlow Pipeline
             │
             ├─ preprocess_features()
             │  log_ret, hl_vol, vol_ratio, ret_std
             │
             ├─ scale_features()
             │  Min-Max → [0.0, 1.0]
             │
             ├─ prepare_sequences()
             │  Rolling Window 10 ngày
             │  → Tensor (N-9, 10, 4)
             │
             ├──► Autoencoder  →  Anomaly Report (MSE + Threshold)
             │
             └──► LSTM         →  Trend Forecast (UP/HOLD/DOWN + Confidence)
```
