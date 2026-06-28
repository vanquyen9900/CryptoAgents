# PHẦN 3: CHI TIẾT CÁC PHƯƠNG PHÁP CẢI TIẾN VÀ KẾT QUẢ RIÊNG BIỆT

Để giải quyết triệt để các hạn chế trên, chúng tôi đã triển khai 5 trụ cột cải tiến can thiệp tại các khâu khác nhau của hệ thống. Dưới đây là mô tả chi tiết giải pháp kỹ thuật theo mã nguồn thực tế và kết quả đo lường riêng biệt của từng phương pháp.

---

## 1. Trụ cột A: Tinh chỉnh mô hình phân tích tâm lý (Sentiment Analyst Fine-tuning)
*   **Giải pháp:** 
    *   Chúng tôi tiến hành fine-tune mô hình nền `qwen3:4b` bằng phương pháp huấn luyện thích ứng thứ hạng thấp lượng tử hóa (**QLoRA**) trên môi trường Colab Pro. Dữ liệu huấn luyện gồm 1.440 mẫu "Golden Response" được sinh thông qua cơ chế chưng cất tri thức (knowledge distillation) từ mô hình lớn `gpt-oss-120b`.
    *   Định dạng dữ liệu đầu vào tuân thủ ChatML, mô hình tinh chỉnh được lượng tử hóa và xuất sang định dạng GGUF để deploy nội bộ qua Ollama.
    *   Chúng tôi áp đặt cấu trúc đầu ra nghiêm ngặt gồm 5 phần bắt buộc: (1) Sentiment Direction, (2) Source Breakdown, (3) Sentiment/Price Divergence, (4) Key Catalysts/Risks, và (5) Markdown Table tổng hợp. Để tránh lỗi cắt cụt văn bản (truncation error) do mô hình suy nghĩ lâu, chúng tôi tăng `max_tokens` từ 1500 lên 3000.
*   **Kết quả đo lường riêng biệt (trên 144 mẫu test độc lập):**

| Cấu hình mô hình | ROUGE-1 F1 | Sentiment Accuracy | Điểm trung bình của Judge (1-5) |
|---|---|---|---|
| `qwen3:4b` (Baseline) | 0.290 | 31.2% | 1.70 |
| `sentiment-analyst-ft` (chưa vá truncation) | 0.934 | 83.3% | 2.99 |
| `sentiment-analyst-ft` (sau khi vá) | **0.962** | **85.4%** | **3.41** |
| *Mức tăng ($\Delta$ vs Baseline)* | *+0.672* | *+54.2%* | *+1.71* |

---

## 2. Trụ cột B: Tác tử nhận diện pha thị trường (HMM Regime Analyst)
*   **Giải pháp:**
    *   Chúng tôi bổ sung node **Regime Analyst** chạy mô hình Markov ẩn (**HMM**) sử dụng thư viện TensorFlow để phân tích chuỗi dữ liệu giá đóng cửa lịch sử. Mô hình phân loại thị trường thành 3 trạng thái động: **Bull (Thị trường tăng)**, **Bear (Thị trường giảm)**, và **Sideway (Thị trường đi ngang)**.
    *   Nhãn pha này được chuyển trực tiếp vào cấu trúc trạng thái (`regime_report`) để làm bộ lọc rủi ro đầu vào cho Portfolio Manager:
        *   *Pha Bull:* Tăng giới hạn tỷ trọng vốn đầu tư tối đa (`target_weight`).
        *   *Pha Bear:* Giảm thiểu exposure, buộc Portfolio Manager chuyển sang trạng thái phòng thủ hoặc đứng ngoài để bảo vệ vốn.
        *   *Pha Sideway:* Thu hẹp tỷ trọng, tránh các giao dịch mua đuổi phá vỡ hộp tích lũy (overtrade).
*   **Kết quả đo lường riêng biệt (Backtest trên mã GOOGL qua 30 chu kỳ, mỗi chu kỳ 5 phiên):**

| Chỉ số hiệu năng | Không có HMM Regime (Baseline) | Có tích hợp HMM Regime | Chiến lược Mua & Giữ (Buy & Hold) |
|---|---|---|---|
| Lợi nhuận tích lũy (CR%) | 10.84% | **19.62%** | 26.58% |
| Sharpe Ratio | 0.91 | **1.42** | 1.45 |
| Sụt giảm tài sản lớn nhất (MDD%) | -13.70% | **-9.36%** | -20.36% |
| Calmar Ratio | 1.39 | **3.83** | 2.39 |
| Độ chính xác hướng giao dịch | 53.33% | **66.67%** | - |

---

## 3. Trụ cột C1: Kho ký ức bài học kinh nghiệm dài hạn (MeMo Bank)
*   **Giải pháp:**
    *   Xây dựng một cơ sở dữ liệu ký ức đóng vai trò như cẩm nang giao dịch lịch sử. Kho ký ức bao gồm 8 "seed memories" mô tả chi tiết các bài học xương máu rút ra từ đợt sụt giảm mạnh năm 2022 để dạy cho tác tử cách phòng thủ, cộng thêm các "weekly lessons" tự động tổng hợp cuối mỗi tuần.
    *   Tác tử chỉ được phép đọc tối đa 5 ký ức phù hợp nhất tại thời điểm quyết định của Portfolio Manager để hạn chế loãng ngữ cảnh prompt.
    *   Áp dụng quy tắc `visible_from` nghiêm ngặt: Ký ức chỉ được hiển thị cho tác tử đọc nếu ngày xảy ra ký ức đó nhỏ hơn ngày giao dịch hiện tại của phiên giao dịch nhằm loại bỏ hoàn toàn lỗi rò rỉ dữ liệu tương lai.
*   **Kết quả đo lường riêng biệt (Giai đoạn Q1/2024):**

| Mã cổ phiếu | Trạng thái thị trường thực tế | Hiệu năng Mua & Giữ | Hiệu năng khi bật MeMo + Risk Aware | Ghi chú tác động |
|---|---|---|---|---|
| **AAPL** | Xu thế giảm mạnh | CR: -7.91%, MDD: 13.50% | **CR: -1.82%, MDD: 3.06%** | Tránh phần lớn lỗ và giảm thiểu sụt giảm vốn đáng kể. |
| **GOOGL** | Biến động mạnh, đi ngang | CR: +12.87%, MDD: 14.40% | **CR: +2.35%, MDD: 1.10%** | Giữ đường vốn cực kỳ ổn định, an toàn tuyệt đối. |
| **AMZN** | Xu thế tăng giá mạnh | CR: +22.26%, MDD: - | **CR: +16.36%, MDD: 4.22%** | Chấp nhận lợi nhuận thấp hơn baseline để ưu tiên phòng thủ. |

---

## 4. Trụ cột C2: Truy xuất ký ức theo pha nhận biết (Regime-aware Vector Retrieval)
*   **Giải pháp:**
    *   Thay thế hoàn toàn cơ chế đọc FIFO cũ bằng **RegimeAwareVectorMemory** tích hợp cơ sở dữ liệu vector **ChromaDB** và mô hình sinh vector đặc trưng `sentence-transformers` (mặc định là `all-MiniLM-L6-v2`).
    *   Quá trình truy xuất diễn ra qua 2 bước tối ưu:
        1.  *Bước 1 (Lọc metadata):* Chỉ trích xuất các ký ức trong kho dữ liệu có nhãn pha trùng với trạng thái thị trường hiện tại do HMM Regime Analyst cung cấp (ví dụ: đang trong Bear Market thì chỉ lấy bài học Bear).
        2.  *Bước 2 (Xếp hạng Cosine):* Tính toán khoảng cách cosine giữa vector truy vấn của tình huống hiện tại và vector của tài liệu phản hồi cũ, xếp hạng và lấy ra 3 bài học tương đồng nhất.
    *   *Cơ chế Fallback:* Nếu hệ thống không cài đặt được các thư viện vector, bộ nhớ tự động chuyển về cơ chế FIFO truyền thống đi kèm cảnh báo để đảm bảo hệ thống không bị crash.
*   **Kết quả đo lường riêng biệt (Tỷ lệ khớp pha thị trường của ký ức được truy xuất):**

| Cơ chế truy xuất ký ức | Tỷ lệ ký ức trùng khớp pha (Same-regime Hit-rate) | Vai trò thực tế |
|---|---|---|
| FIFO truyền thống (Baseline) | ~41% | Tham chiếu ngẫu nhiên, dễ bị lệch pha |
| **Regime-aware Vector (Đề xuất)** | **~88%** | Cung cấp đúng ngữ cảnh bài học phù hợp với pha hiện tại |

---

## 5. Trụ cột D: Tranh luận thích ứng và Chỉ báo Crypto (Adaptive Debate & Crypto Indicators)
*   **Giải pháp 1: Cơ chế tranh luận thích ứng (Adaptive Debate)**
    *   Thay vì chạy đủ 3 vòng tranh luận cố định, chúng tôi yêu cầu Bull Researcher và Bear Researcher xuất ra điểm số tự tin cá nhân $C \in [0, 1]$ ở cuối mỗi luận điểm.
    *   Tại mỗi vòng tranh luận $k$, hệ thống tính toán chỉ số đồng thuận: $S_k = 1 - |C_{bull} - C_{bear}|$.
    *   Hệ thống sẽ kết thúc sớm vòng tranh luận (early stopping) ngay khi đạt được sự đồng thuận $S_k \ge \theta$ (mặc định $\theta = 0.75$) hoặc chạm mức cap cứng $K_{max} = 3$ vòng (tương đương tối đa 6 lượt hội thoại).
*   **Giải pháp 2: Chỉ báo đặc trưng Crypto (Crypto-native Indicators)**
    *   Khi cấu hình tài sản là tiền mã hóa (`asset_type == "crypto"`), hệ thống kích hoạt công cụ `get_crypto_indicators` để tải về các chỉ số: Fear & Greed Index (FNG), Bitcoin Dominance (DOM), Funding Rate (FR) và Open Interest (OI) thông qua API công cộng (alternative.me, Coingecko, Binance).
    *   Tác tử Market Analyst sử dụng các chỉ số này để chạy logic heuristic phát hiện rủi ro thanh lý hàng loạt (squeeze risk):
        *   *Long Squeeze Risk:* FNG > 85 (Tham lam cực độ) + FR > 0.05% (Long đang trả phí rất cao cho Short) + OI tăng mạnh.
        *   *Short Squeeze Risk:* FNG < 15 (Sợ hãi cực độ) + FR < -0.05% (Short đang trả phí cho Long) + OI tăng cao.
*   **Kết quả đo lường riêng biệt:**

**Hiệu năng tiết kiệm Token và Chi phí tranh luận (Adaptive Debate):**

| Cấu hình số vòng tranh luận | Số vòng trung bình thực tế | Lượng token tiêu thụ tương đối |
|---|---|---|
| Cố định $K = 1$ vòng | 1.00 vòng | 1.00x |
| Cố định $K = 3$ vòng (Baseline) | 3.00 vòng | 2.95x |
| **Thích ứng (Adaptive $\theta = 0.75$)** | **1.80 vòng** | **2.12x** (Tiết kiệm ~28% chi phí API) |

**Hiệu năng phân tích tài sản mã hóa (Backtest BTC và ETH cả năm 2024):**

| Tài sản kiểm thử | Cấu hình kiểm thử | Lợi nhuận tích lũy (CR%) | Sharpe Ratio | Sụt giảm vốn tối đa (MDD%) |
|---|---|---|---|---|
| **BTC** | Baseline (Không chỉ báo Crypto) | 22.0% | 1.05 | -24.0% |
| **BTC** | **Tích hợp chỉ báo Crypto** | **27.5%** | **1.31** | **-19.5%** |
| **ETH** | Baseline (Không chỉ báo Crypto) | 25.0% | 1.00 | -28.0% |
| **ETH** | **Tích hợp chỉ báo Crypto** | **31.0%** | **1.22** | **-22.5%** |
