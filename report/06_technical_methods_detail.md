# PHẦN 6: CHI TIẾT CÁC PHƯƠNG THỨC TRONG CODEBASE CẢI TIẾN

Tài liệu này trình bày chi tiết đặc tả kỹ thuật, tham số đầu vào/đầu ra, logic thuật toán và mã nguồn thực tế (Python Code Snippets) của từng phương thức (methods) đã được chỉnh sửa hoặc thêm mới để phục vụ cho các cải tiến của **CryptoAgents**.

---

## 1. Trụ cột D: Nhóm phương thức lấy chỉ báo Crypto (dataflows/crypto_indicators.py)

Mục tiêu của module này là thu thập các thông số thị trường tiền mã hóa đặc trưng và đánh giá rủi ro thanh lý hợp đồng phái sinh.

### 1.1 `fetch_fng(limit: int = 3) -> List[dict]`
*   **Chức năng:** Lấy lịch sử chỉ số Fear & Greed Index (FNG) của thị trường Crypto từ API `alternative.me`.
*   **Tham số:**
    *   `limit` (int): Số lượng ngày lịch sử cần lấy (mặc định = 3).
*   **Logic xử lý & Fallback:** Gửi request HTTP GET tới `https://api.alternative.me/fng/?limit={limit}`. Nếu gặp sự cố mạng (HTTP Error, Connection Timeout), phương thức bắt lỗi `Exception`, ghi log warning và trả về danh sách trống `[]`.
*   **Đầu ra:** Một list các dict chứa `value` (chuỗi dạng số nguyên từ 0-100) và `value_classification` (Extreme Fear, Fear, Neutral, Greed, Extreme Greed).
*   **Mã nguồn thực tế:**
```python
def fetch_fng(limit: int = 3) -> List[dict]:
    url = f"https://api.alternative.me/fng/?limit={limit}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])
    except Exception as e:
        logger.warning("Error fetching Fear & Greed Index: %s. Using empty list.", e)
        return []
```

### 1.2 `fetch_btc_dominance(limit_days: int = 5) -> float`
*   **Chức năng:** Lấy tỷ lệ vốn hóa của Bitcoin so với toàn bộ thị trường tiền mã hóa (Bitcoin Dominance %) từ API công cộng của `CoinGecko`.
*   **Tham số:**
    *   `limit_days` (int): Số ngày lịch sử để kiểm tra.
*   **Logic xử lý & Fallback:** Gửi request HTTP GET tới `https://api.coingecko.com/api/v3/global`. Trích xuất trường dữ liệu `market_cap_percentage` -> `btc`. Nếu API chặn request hoặc lỗi mạng, bắt lỗi trả về giá trị mặc định `55.0` kèm log cảnh báo.
*   **Mã nguồn thực tế:**
```python
def fetch_btc_dominance(limit_days: int = 5) -> float:
    url = "https://api.coingecko.com/api/v3/global"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        btc_dom = data.get("data", {}).get("market_cap_percentage", {}).get("btc", 55.0)
        return float(btc_dom)
    except Exception as e:
        logger.warning("Error fetching BTC dominance: %s. Using default 55.0", e)
        return 55.0
```

### 1.3 `fetch_funding_rate(symbol: str, limit: int = 10) -> List[dict]`
*   **Chức năng:** Truy vấn tỷ lệ lệ phí tài trợ (Funding Rate - FR) hiện tại và lịch sử của hợp đồng tương lai vĩnh cửu (Perpetual Futures) từ sàn giao dịch `Binance`.
*   **Mã nguồn thực tế:**
```python
def fetch_funding_rate(symbol: str, limit: int = 10) -> List[dict]:
    base = _base_asset(symbol)
    binance_symbol = f"{base}USDT"
    url = f"https://fapi.binance.com/fapi/v1/fundingRate?symbol={binance_symbol}&limit={limit}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning("Error fetching Funding Rate for %s: %s", symbol, e)
        return []
```

### 1.4 `fetch_open_interest(symbol: str, limit: int = 10) -> List[dict]`
*   **Chức năng:** Lấy tổng số lượng vị thế hợp đồng tương lai đang mở (Open Interest - OI) tính theo đơn vị tài sản và quy đổi USD từ sàn `Binance`.
*   **Mã nguồn thực tế:**
```python
def fetch_open_interest(symbol: str, limit: int = 10) -> List[dict]:
    base = _base_asset(symbol)
    binance_symbol = f"{base}USDT"
    url = f"https://fapi.binance.com/fapi/v1/openInterest/hist?symbol={binance_symbol}&period=5m&limit={limit}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.warning("Error fetching Open Interest for %s: %s", symbol, e)
        return []
```

### 1.5 `evaluate_squeeze_risk(fng_value: int, fr: float, oi_usd: float) -> dict`
*   **Chức năng:** Logic heuristic cốt lõi để tính toán rủi ro thanh lý hợp đồng phái sinh dựa trên sự kết hợp đồng thời của cả 3 yếu tố: sentiment cực đoan, đòn bẩy thị trường cao, và phí funding lệch lớn.
*   **Mã nguồn thực tế:**
```python
def evaluate_squeeze_risk(fng_value: int, fr: float, oi_usd: float) -> dict:
    # Ngưỡng kích hoạt rủi ro thanh lý
    fng_extreme_greed = 85
    fng_extreme_fear = 15
    fr_high_threshold = 0.0005    # 0.05%
    fr_low_threshold = -0.0005    # -0.05%
    oi_high_threshold = 5e9       # 5 tỷ USD đòn bẩy tích lũy

    is_greed = fng_value >= fng_extreme_greed
    is_fear = fng_value <= fng_extreme_fear
    is_fr_long_crowded = fr >= fr_high_threshold
    is_fr_short_crowded = fr <= fr_low_threshold
    is_oi_high = oi_usd >= oi_high_threshold

    # Đếm số điều kiện thỏa mãn
    greed_conditions = sum([is_greed, is_fr_long_crowded, is_oi_high])
    fear_conditions = sum([is_fear, is_fr_short_crowded, is_oi_high])

    if greed_conditions == 3:
        return {"squeeze_type": "long_squeeze_risk", "signal_strength": "high"}
    elif fear_conditions == 3:
        return {"squeeze_type": "short_squeeze_risk", "signal_strength": "high"}
    elif greed_conditions == 2:
        return {"squeeze_type": "long_squeeze_risk", "signal_strength": "medium"}
    elif fear_conditions == 2:
        return {"squeeze_type": "short_squeeze_risk", "signal_strength": "medium"}
    
    return {"squeeze_type": "none", "signal_strength": "none"}
```

---

## 2. Tương tác Agent & Tool (agents/utils/crypto_indicator_tools.py)

### 2.1 `@tool get_crypto_indicators(symbol: str) -> str`
*   **Chức năng:** Lớp bao bọc (Wrapper) sử dụng decorator `@tool` của LangChain để biến hàm `get_crypto_native_indicators` thành một công cụ có thể gọi tự động (Tool Calling) bởi mô hình ngôn ngữ lớn.
*   **Mã nguồn thực tế:**
```python
@tool
def get_crypto_indicators(symbol: str) -> str:
    """Retrieve crypto-native sentiment and leverage metrics (FNG, DOM, FR, OI)
    and compute dynamic liquidation squeeze risk indicators.
    """
    return get_crypto_native_indicators(symbol)
```

---

## 3. Lớp quyết định Graph Flow (graph/conditional_logic.py)

### 3.1 `should_continue_debate(state: AgentState) -> str`
*   **Chức năng:** Quyết định dừng sớm (early stopping) cuộc tranh luận giữa Bull và Bear Researcher dựa trên độ đồng thuận tự báo cáo hoặc chuyển đổi lượt nói.
*   **Mã nguồn thực tế:**
```python
def should_continue_debate(self, state: AgentState) -> str:
    ds = state["investment_debate_state"]
    count = ds["count"]
    hard_cap = 2 * self.adaptive_debate_k_max  # K_max rounds = 2*K_max turns

    # ── Hard cap (luôn luôn được tôn trọng)
    if count >= hard_cap:
        logger.debug("Debate stopped: hard cap reached (count=%d, cap=%d)", count, hard_cap)
        return "Research Manager"

    # ── Kiểm tra đồng thuận (cần ít nhất 1 vòng trao đổi đầy đủ)
    if count >= 2:
        c_bull = ds.get("bull_confidence", 0.5)
        c_bear = ds.get("bear_confidence", 0.5)
        s_k = 1.0 - abs(c_bull - c_bear)
        logger.debug(
            "Debate round count=%d: C_bull=%.2f C_bear=%.2f S_k=%.2f theta=%.2f",
            count, c_bull, c_bear, s_k, self.adaptive_debate_theta,
        )
        if s_k >= self.adaptive_debate_theta:
            logger.debug("Debate stopped: consensus reached (S_k=%.2f >= θ=%.2f)", s_k, self.adaptive_debate_theta)
            return "Research Manager"

    # ── Tiếp tục: luân phiên chuyển đổi quyền nói
    if ds["current_response"].startswith("Bull"):
        return "Bear Researcher"
    return "Bull Researcher"
```

---

## 4. Tác tử tranh luận & phản hồi (agents/researchers/bull_researcher.py & bear_researcher.py)

### 4.1 `_parse_confidence(text: str) -> float`
*   **Chức năng:** Trích xuất điểm số tự tin từ phản hồi thô của LLM bằng biểu thức chính quy.
*   **Mã nguồn thực tế:**
```python
def _parse_confidence(text: str) -> float:
    matches = re.findall(r"CONFIDENCE:\s*([0-9]*\.?[0-9]+)", text, re.IGNORECASE)
    if not matches:
        return 0.5
    try:
        value = float(matches[-1])
        return max(0.0, min(1.0, value))  # Giới hạn trong khoảng [0.0, 1.0]
    except ValueError:
        return 0.5
```

---

## 5. Lớp Vector Memory (agents/utils/vector_memory.py)

### 5.1 `_ngram_embed(text: str, dim: int = 128) -> List[float]`
*   **Chức năng:** Hàm sinh vector pseudo-embedding dựa trên tần suất xuất hiện ký tự n-gram (fallback khi không có thư viện `sentence-transformers`).
*   **Mã nguồn thực tế:**
```python
def _ngram_embed(text: str, dim: int = 128) -> List[float]:
    import hashlib
    vec = [0.0] * dim
    text_norm = text.lower()
    for i in range(len(text_norm) - 2):
        tri = text_norm[i : i + 3]
        h = int(hashlib.md5(tri.encode()).hexdigest(), 16) % dim
        vec[h] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]
```

### 5.2 `RegimeAwareVectorMemory.retrieve(...)`
*   **Chức năng:** Thực hiện truy xuất 2 bước: lọc metadata theo pha thị trường sau đó xếp hạng độ tương đồng cosine.
*   **Mã nguồn thực tế:**
```python
def retrieve(
    self,
    *,
    ticker: str,
    regime: str,
    query_text: str,
    top_k: Optional[int] = None,
) -> List[dict]:
    if not self._available or self._collection.count() == 0:
        return []

    k = top_k or self.top_k
    regime_tag = regime if regime in self.REGIME_LABELS else "Sideway"
    query_embedding = self._embed(query_text)

    # ── Bước 1: Lọc pre-filter theo regime (Bull/Bear/Sideway hoặc ANY)
    try:
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k * 4, self._collection.count()),  # over-fetch
            where={"regime": {"$in": [regime_tag, "ANY"]}},
            include=["documents", "metadatas"],
        )
    except Exception as exc:
        logger.warning("VectorMemory: ChromaDB query failed: %s", exc)
        return []

    # ── Bước 2: Trích xuất danh sách đã xếp hạng bởi ChromaDB
    memories = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]

    for doc, meta in zip(docs, metas):
        memories.append({
            "ticker": meta.get("ticker", ""),
            "regime": meta.get("regime", ""),
            "trade_date": meta.get("trade_date", ""),
            "rating": meta.get("rating", ""),
            "raw_return": meta.get("raw_return", 0.0),
            "alpha_return": meta.get("alpha_return", 0.0),
            "reflection": doc,
        })
        if len(memories) >= k:
            break

    return memories
```

---

## 6. Lớp điều phối bộ nhớ (agents/utils/memory.py)

### 6.1 `TradingMemoryLog.get_past_context(...)`
*   **Chức năng:** Lấy toàn bộ ngữ cảnh kinh nghiệm quá khứ (Cử vector memory ChromaDB hoặc FIFO fallback).
*   **Mã nguồn thực tế:**
```python
def get_past_context(self, ticker: str, n_same: int = 5, n_cross: int = 3, regime: str = "") -> str:
    # ── Nhánh C2 Vector Memory
    if self._vector_memory is not None and regime and self._vector_memory.available:
        query = f"Trading decision for {ticker} in {regime} regime"
        memories = self._vector_memory.retrieve(
            ticker=ticker,
            regime=regime,
            query_text=query,
        )
        if memories:
            return self._vector_memory.format_for_prompt(memories)

    # ── Nhánh FIFO Fallback gốc
    entries = [e for e in self.load_entries() if not e.get("pending")]
    if not entries:
        return ""

    same, cross = [], []
    for e in reversed(entries):
        if len(same) >= n_same and len(cross) >= n_cross:
            break
        if e["ticker"] == ticker and len(same) < n_same:
            same.append(e)
        elif e["ticker"] != ticker and len(cross) < n_cross:
            cross.append(e)

    if not same and not cross:
        return ""

    parts = []
    if same:
        parts.append(f"Past analyses of {ticker} (most recent first):")
        parts.extend(self._format_full(e) for e in same)
    if cross:
        parts.append("Recent cross-ticker lessons:")
        parts.extend(self._format_reflection_only(e) for e in cross)
    return "\n\n".join(parts)
```
