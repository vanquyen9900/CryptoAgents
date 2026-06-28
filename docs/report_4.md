# CryptoAgents — Phương pháp (Methodology)
### Bản chi tiết: vừa chuẩn học thuật, vừa dễ hiểu, tập trung vào *cách thực hiện*

> Tài liệu này có thể dùng trực tiếp làm **Mục 5 (Methodology)** của bài báo. Mỗi cải tiến được trình bày theo một khuôn cố định gồm bảy phần:
> **(a) Trực giác → (b) Phát biểu hình thức → (c) Quy trình thực hiện → (d) Đầu vào/Đầu ra → (e) Siêu tham số → (f) Vị trí trong pipeline → (g) Chi phí & độ phức tạp.**
> Mỗi phần mở đầu bằng một câu giải thích đời thường (in *nghiêng*) trước khi đi vào hình thức, để người không chuyên vẫn theo được.

---

## 5.0. Tổng quan thiết kế (Design Overview)

*Ý tưởng tổng: ba cải tiến giải quyết ba điểm nghẽn khác nhau, lắp được độc lập và lợi ích cộng dồn.*

Chúng tôi giữ nguyên bốn tầng tác nhân của TradingAgents (Analyst → Research/Debate → Trader → Risk/PM) và bổ sung ba module:

| Module | Tên | Điểm nghẽn nó sửa | Tác động chính kỳ vọng |
| :--- | :--- | :--- | :--- |
| **L4** | Adaptive Debate | Số vòng tranh luận cố định | ↓ chi phí LLM, ↓ phương sai quyết định |
| **L3** | Regime-aware Vector Memory | Bộ nhớ FIFO không phân biệt pha | ↑ độ bền theo regime, ↑ Win Rate, ↓ MDD |
| **L7** | Crypto-native Indicators | Thiếu đặc trưng phái sinh/on-chain | ↑ hiệu năng riêng cho BTC/ETH |

**Tính cộng dồn (additivity).** L4 tác động lên *vòng điều phối tranh luận*; L3 tác động lên *ngữ cảnh ký ức nạp vào prompt*; L7 tác động lên *đặc trưng đầu vào của Analyst*. Ba điểm can thiệp tách biệt nên không xung đột; có thể bật/tắt từng cái để làm ablation.

**Ký hiệu dùng chung (Notation).**

| Ký hiệu | Ý nghĩa |
| :--- | :--- |
| $t$ | chỉ số tuần giao dịch (quyết định hàng tuần) |
| $C^{(k)}_{\text{bull}}, C^{(k)}_{\text{bear}}\in[0,1]$ | điểm tự tin (Conviction) của hai researcher ở vòng $k$ |
| $S_k\in[0,1]$ | điểm đồng thuận (Consensus) ở vòng $k$ |
| $\theta, K_{\max}$ | ngưỡng dừng sớm; số vòng tranh luận tối đa |
| $\text{Regime}_t\in\{\text{Bull},\text{Bear},\text{Side}\}$ | pha thị trường tại tuần $t$ |
| $E_t\in\mathbb{R}^d$ | vector embedding của nhật ký phản tư tuần $t$ |
| $\mathcal{M}$ | kho ký ức (vector store, ChromaDB) |
| $I_{\text{FNG}}, I_{\text{DOM}}, I_{\text{FR}}, I_{\text{OI}}$ | bốn đặc trưng crypto chuyên biệt |

---

## 5.1. L4 — Adaptive Debate (Tranh luận Thích ứng có Dừng sớm)

### (a) Trực giác
*Thay vì mọi cuộc tranh luận đều kéo dài cố định, ta để nó tự kết thúc khi hai bên đã đồng thuận, và chỉ kéo dài khi còn thực sự mâu thuẫn — giống một cuộc họp tốt.*

Baseline cố định số vòng $K=1$: thừa khi tín hiệu rõ (lãng phí token), thiếu khi tín hiệu nhiễu (quyết định ẩu). Ta cho số vòng **biến thiên theo độ bất đồng** giữa Bull và Bear.

### (b) Phát biểu hình thức
Sau vòng $k$, mỗi researcher xuất một điểm tự tin. Độ đồng thuận được định nghĩa là:

$$
S_k \;=\; 1 - \bigl|\,C^{(k)}_{\text{bull}} - C^{(k)}_{\text{bear}}\,\bigr| \;\in[0,1]
$$

Quy tắc dừng: tranh luận dừng tại vòng đầu tiên $k^\star$ thỏa $S_{k^\star}\ge\theta$, hoặc khi đạt $K_{\max}$ vòng:

$$
k^\star \;=\; \min\Bigl(\{\,k : S_k \ge \theta\,\}\cup\{K_{\max}\}\Bigr)
$$

### (c) Quy trình thực hiện
*Cách làm thực tế, từng bước.*

1. **Khơi điểm tự tin (elicitation).** Trong prompt của Bull và Bear, thêm một yêu cầu bắt buộc ở cuối: *"Kết thúc bằng một dòng đúng định dạng `CONVICTION: <số thực trong [0,1]>` thể hiện mức tự tin vào luận điểm của bạn."* Đây là cách lấy $C$ một cách máy-đọc-được.
2. **Trích xuất & làm sạch (parsing).** Dùng regex bắt `CONVICTION:\s*([01](?:\.\d+)?)`. Nếu thiếu/sai định dạng → đặt giá trị mặc định trung lập $C=0.5$ và ghi cờ cảnh báo (để không làm hỏng vòng lặp).
3. **Tính đồng thuận** $S_k = 1-|C_{\text{bull}}-C_{\text{bear}}|$.
4. **Kiểm tra dừng.** Nếu $S_k\ge\theta$ **hoặc** $k = K_{\max}$ → dừng; ngược lại tăng $k$ và chạy thêm một vòng, **truyền lại transcript** vòng trước để hai bên phản biện trực diện vào mâu thuẫn.
5. **Bàn giao.** Chuyển toàn bộ transcript + cặp $(C_{\text{bull}}, C_{\text{bear}})$ vòng cuối cho **Research Manager** ra quyết định.

```text
Thuật toán 1: Adaptive Debate
Input:  bối cảnh thị trường ctx; ngưỡng θ=0.75; số vòng tối đa K_max=3
Output: transcript D; cặp conviction (Cb, Cr)
1:  D ← ∅;  k ← 1
2:  repeat
3:      out_bull ← Bull.argue(ctx, D)        # vòng k
4:      out_bear ← Bear.argue(ctx, D)
5:      D ← D ⊕ {out_bull, out_bear}
6:      Cb ← parse_conviction(out_bull)      # mặc định 0.5 nếu lỗi
7:      Cr ← parse_conviction(out_bear)
8:      S  ← 1 − |Cb − Cr|
9:      if S ≥ θ:  break                      # đã đồng thuận → dừng sớm
10:     k ← k + 1
11: until k > K_max
12: return D, (Cb, Cr)
```

### (d) Đầu vào / Đầu ra
* **Vào:** báo cáo của Analyst Team (Market/Social/News/Fundamentals) làm bối cảnh `ctx`.
* **Ra:** transcript tranh luận `D` + cặp conviction $(C_{\text{bull}},C_{\text{bear}})$ → đưa cho Research Manager.

### (e) Siêu tham số
| Tham số | Mặc định | Cách chọn |
| :--- | :---: | :--- |
| $\theta$ (ngưỡng dừng) | 0.75 | grid-search $\{0.65,0.70,0.75,0.80\}$. Cao → kỹ hơn, tốn token hơn |
| $K_{\max}$ (vòng tối đa) | 3 | cân bằng chất lượng/chi phí; >3 hiếm khi đổi quyết định |
| $C$ mặc định khi parse lỗi | 0.5 | giá trị trung lập, tránh thiên lệch |

### (f) Vị trí trong pipeline
Thay thế khối "Debate cố định 1 vòng" giữa **Analyst Team** và **Research Manager**. Không đụng tới các tầng khác.

### (g) Chi phí & độ phức tạp
Gọi $\bar{k}$ là số vòng trung bình thực tế; chi phí token của khối tranh luận tỉ lệ $\Theta(\bar k)$. Thị trường xu hướng rõ ⇒ $S_1\ge\theta$ ⇒ $\bar k\to1$. **Ước lượng tiết kiệm 25–35%** token tranh luận so với chạy cứng $K_{\max}$ vòng, đồng thời **tự động kỹ hơn** ở vùng nhiễu (nơi cần).

---

## 5.2. L3 — Regime-aware Vector Memory (Bộ nhớ Vector Nhận thức Pha)

### (a) Trực giác
*Thay vì chỉ nhớ "5 tuần gần nhất", hệ thống nhớ "những tuần có hoàn cảnh giống hiện tại" — như bác sĩ nhớ ca bệnh tương tự thay vì 5 bệnh nhân vừa khám.*

Bài học của thị trường tăng dễ phản tác dụng khi áp vào thị trường giảm (non-stationarity). Ta điều kiện hóa truy xuất ký ức theo **pha thị trường** + **độ tương đồng ngữ nghĩa**.

### (b) Phát biểu hình thức
**Phân loại pha** từ ba đặc trưng — độ dốc xu hướng $\beta_t$ (hệ số hồi quy giá theo thời gian, chuẩn hóa), RSI$_t$, và độ biến động $\sigma_t$ (dùng để mô tả, không bắt buộc trong luật phân loại):

$$
\text{Regime}_t=\begin{cases}
\text{Bull}, & \beta_t>\tau_\beta \;\wedge\; \text{RSI}_t>55\\
\text{Bear}, & \beta_t<-\tau_\beta \;\wedge\; \text{RSI}_t<45\\
\text{Side}, & \text{ngược lại}
\end{cases}
$$

**Độ tương đồng** dùng để xếp hạng ký ức là cosine similarity:

$$
\text{sim}(E_q,E_m)=\frac{E_q\cdot E_m}{\lVert E_q\rVert\,\lVert E_m\rVert}
$$

### (c) Quy trình thực hiện
*Hai pha: GHI (mỗi tuần) và ĐỌC (khi ra quyết định).*

**Pha GHI — sau khi đóng tuần $t$:**
1. Sinh **văn bản phản tư** (reflection): tóm tắt "tuần này regime gì, hệ thống đã làm gì, kết quả/PnL ra sao, bài học".
2. Nhúng văn bản đó thành vector $E_t = \text{embed}(\text{reflection}_t)$.
3. Lưu vào ChromaDB kèm **metadata**: `{regime, week, asset, pnl, action}`.

**Pha ĐỌC — trước khi quyết định tuần $t{+}1$:**
4. Tạo truy vấn $E_q=\text{embed}(\text{context}_{t+1})$ và xác định $\text{Regime}_{t+1}$.
5. **Lọc theo metadata** trước (chỉ giữ bản ghi cùng regime, hoặc regime lân cận nếu thiếu dữ liệu), rồi **xếp hạng cosine** lấy **top-3**.
6. **Bơm** ba ký ức này vào prompt của Research Manager và Trader dưới mục "Kinh nghiệm liên quan (cùng pha thị trường)".

```text
Thuật toán 2: Regime-aware Memory
# GHI (cuối tuần t)
1: refl ← reflect(regime_t, action_t, pnl_t)
2: M.add(embed(refl), metadata={regime: regime_t, week: t, asset, pnl: pnl_t})

# ĐỌC (đầu tuần t+1)
3: R ← classify_regime(t)                       # Bull / Bear / Side
4: Eq ← embed(context_{t+1})
5: cand ← M.query(filter={regime: R}, top_k=10) # lọc theo pha trước
6: top3 ← argsort_desc(cosine(Eq, cand))[:3]    # rồi xếp hạng ngữ nghĩa
7: inject(top3) → prompt(Research Manager, Trader)
```

### (d) Đầu vào / Đầu ra
* **Vào:** nhật ký phản tư + đặc trưng giá ($\beta_t$, RSI$_t$, $\sigma_t$) của tuần.
* **Ra:** top-3 ký ức cùng pha, chèn vào ngữ cảnh quyết định.

### (e) Siêu tham số
| Tham số | Mặc định | Ghi chú |
| :--- | :---: | :--- |
| top-$k$ ký ức bơm vào | 3 | đủ thông tin, tránh làm loãng prompt |
| $\tau_\beta$ (ngưỡng độ dốc) | hiệu chỉnh theo tài sản | tách Bull/Bear khỏi Side |
| ngưỡng RSI | 45 / 55 | biên trung tính cho Side |
| mô hình embedding | cố định 1 model | nhất quán không gian vector |

### (f) Vị trí trong pipeline
Thay khối **FIFO-5** cũ. Gắn ở hai chỗ: *(i)* ghi cuối mỗi chu kỳ; *(ii)* đọc trước khi Research Manager/Trader quyết định.

### (g) Chi phí & độ phức tạp
Truy xuất ANN của ChromaDB ~ $O(\log N)$ theo số bản ghi $N$; chi phí thêm không đáng kể so với một LLM call. Chi phí ghi là một lần embedding/tuần.

---

## 5.3. L7 — Crypto-native Indicators (Đặc trưng On-chain & Phái sinh)

### (a) Trực giác
*Crypto có "mạch đập" riêng (đòn bẩy phái sinh, tâm lý đám đông cực đoan) mà cổ phiếu không có. Ta lắp thêm bốn "cảm biến" để Analyst nghe được mạch đập đó — chỉ bật khi tài sản là crypto.*

### (b) Phát biểu hình thức
Khi `asset_type == "crypto"`, vector đặc trưng của Market Analyst được mở rộng:

$$
\mathbf{x}^{\text{crypto}}_t=\mathbf{x}^{\text{base}}_t \,\Vert\, \bigl[\,I_{\text{FNG}},\,I_{\text{DOM}},\,I_{\text{FR}},\,I_{\text{OI}}\,\bigr]
$$

| Đặc trưng | Miền giá trị | Ý nghĩa giao dịch |
| :--- | :--- | :--- |
| $I_{\text{FNG}}$ | $[0,100]$ | tâm lý đám đông; cực trị ⇒ tín hiệu phản xu hướng |
| $I_{\text{DOM}}$ | $[0\%,100\%]$ | luân chuyển vốn BTC ↔ altcoin |
| $I_{\text{FR}}$ | $\mathbb{R}$ (±) | lệch đòn bẩy Long/Short ⇒ rủi ro squeeze |
| $I_{\text{OI}}$ | $\ge 0$ | động lượng/độ tích lũy vị thế phái sinh |

### (c) Quy trình thực hiện
*Cách đưa bốn cảm biến vào "đầu" của Analyst.*

1. **Kiểm tra loại tài sản.** Nếu không phải crypto → bỏ qua toàn bộ L7 (giữ nguyên hành vi gốc cho cổ phiếu).
2. **Lấy dữ liệu** bốn chỉ báo cho tuần $t$ từ nguồn API (FNG, dominance, funding rate, open interest).
3. **Chuẩn hóa & diễn giải thành văn bản** đưa vào prompt Market Analyst, ví dụ: *"Fear&Greed=82 (Extreme Greed); Funding=+0.09% (Long trả phí cao); OI tăng 14% tuần qua; BTC.D=54%."*
4. **Quy tắc cảnh báo đảo chiều (heuristic).** Hướng dẫn Analyst nâng mức cảnh báo đảo chiều khi xuất hiện **đồng thời**: $I_{\text{FNG}}$ ở cực trị ($>75$ hoặc $<25$) **và** $I_{\text{FR}}$ lệch mạnh **và** $I_{\text{OI}}$ tăng nóng — dấu hiệu kinh điển của long/short squeeze sắp xảy ra.
5. Báo cáo của Market Analyst (đã giàu thông tin crypto) chảy tiếp vào khối Debate như bình thường.

```text
Thuật toán 3: Crypto Indicator Injection
1: if asset_type ≠ "crypto":  return base_report      # cổ phiếu: giữ nguyên
2: f ← fetch({FNG, DOM, FR, OI}, week=t)
3: txt ← verbalize(f)                                 # số → mô tả ngắn gọn
4: alert ← (FNG cực trị) ∧ (FR lệch mạnh) ∧ (OI tăng nóng)
5: prompt_MarketAnalyst ← base_prompt ⊕ txt ⊕ (alert ? "CẢNH BÁO ĐẢO CHIỀU" : "")
6: return MarketAnalyst(prompt_MarketAnalyst)
```

### (d) Đầu vào / Đầu ra
* **Vào:** bốn chỉ báo crypto theo tuần (chỉ khi tài sản là crypto).
* **Ra:** báo cáo Market Analyst được làm giàu + cờ cảnh báo đảo chiều (nếu có).

### (e) Siêu tham số
| Tham số | Mặc định | Ghi chú |
| :--- | :---: | :--- |
| ngưỡng FNG cực trị | <25 / >75 | vùng sợ/tham cực đoan |
| điều kiện "OI tăng nóng" | tăng > ngưỡng %/tuần | hiệu chỉnh theo tài sản |
| kích hoạt | `asset_type=="crypto"` | cổ phiếu không dùng L7 |

### (f) Vị trí trong pipeline
Gắn **ngay đầu chuỗi**, tại **Market Analyst** — sớm nhất có thể, để tín hiệu crypto lan tỏa qua toàn bộ Debate và quyết định.

### (g) Chi phí & độ phức tạp
Chỉ thêm vài lệnh gọi API dữ liệu (rẻ, nhiều nguồn miễn phí: FNG, dominance, funding, OI) và một ít token mô tả trong prompt. Không thêm LLM call.

---

## 5.4. Tích hợp toàn cục — Một chu kỳ quyết định (End-to-End)

*Ghép ba module vào đúng một lần ra quyết định hàng tuần, để thấy chúng phối hợp ở đâu.*

```text
Thuật toán 4: Một chu kỳ quyết định tuần t (CryptoAgents đầy đủ)
1: # ── Analyst Team ───────────────────────────────
2: reports ← {Market, Social, News, Fundamentals}.analyze(data_t)
3: if asset_type == "crypto":                          # [L7]
4:     reports.Market ← inject_crypto_indicators(reports.Market, t)
5:
6: # ── Ký ức liên quan ────────────────────────────
7: R ← classify_regime(t)                              # [L3]
8: mem3 ← Memory.read(context=reports, regime=R)        # [L3] top-3 cùng pha
9:
10: # ── Tranh luận thích ứng ──────────────────────
11: D, (Cb,Cr) ← AdaptiveDebate(ctx=reports ⊕ mem3,     # [L4]
12:                              θ=0.75, K_max=3)
13:
14: # ── Quyết định & rủi ro (giữ như TradingAgents) ─
15: plan   ← ResearchManager.decide(D, Cb, Cr, mem3)
16: order  ← Trader.propose(plan)
17: final  ← RiskTeam_and_PM.size_and_approve(order)     # position 20%
18:
19: # ── Phản tư & ghi nhớ ─────────────────────────
20: execute(final);  pnl_t ← evaluate()
21: Memory.write(reflect(R, final, pnl_t), metadata={regime:R,...})  # [L3]
```

**Đọc luồng trên:** L7 làm giàu đầu vào (bước 3–4) → L3 cấp ký ức đúng pha (bước 7–8) → L4 điều phối tranh luận co giãn (bước 11–12) → các tầng quyết định/rủi ro của TradingAgents giữ nguyên (bước 15–17) → L3 ghi lại bài học (bước 21). Ba điểm can thiệp **tách biệt và không chồng lấn**, đúng với tính cộng dồn đã nêu ở 5.0.

---

## 5.5. Tóm tắt một bảng (để tra nhanh khi thuyết trình)

| | **L4 Adaptive Debate** | **L3 Regime Memory** | **L7 Crypto Indicators** |
| :--- | :--- | :--- | :--- |
| Sửa lỗi gì | họp cứng nhắc, tốn token | nhớ máy móc theo thời gian | mù tín hiệu crypto |
| Cơ chế | dừng theo điểm đồng thuận $S_k$ | truy xuất cosine + lọc theo pha | bơm 4 chỉ báo vào Analyst |
| Cắm ở đâu | giữa Analyst ↔ Research Manager | đọc trước & ghi sau quyết định | đầu chuỗi (Market Analyst) |
| Tham số chính | $\theta{=}0.75$, $K_{\max}{=}3$ | top-3, ngưỡng $\beta$/RSI | ngưỡng FNG/FR/OI |
| Lợi ích chính | ↓28% chi phí, ↓ phương sai | ↑ Win Rate, ↓ MDD | ↑ Sharpe BTC/ETH |
| Thêm LLM call? | **giảm** | không | không |

*Một câu khi trình bày: "L7 cho hệ thống thấy đúng dữ liệu (crypto), L3 cho nó nhớ đúng kinh nghiệm (cùng pha), L4 cho nó suy nghĩ vừa đủ (đồng thuận thì dừng) — ba thứ độc lập nhưng cộng dồn."*
