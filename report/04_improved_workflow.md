# PHẦN 4: WORKFLOW HỆ THỐNG SAU KHI CẢI TIẾN (IMPROVED WORKFLOW)

Hệ thống sau khi tích hợp toàn bộ 5 trụ cột cải tiến vẫn giữ cấu trúc StateGraph của LangGraph nhưng được bổ sung các dòng dữ liệu thông minh và các node ra quyết định động. Sơ đồ dưới đây mô tả chi tiết luồng xử lý toàn diện của hệ thống cải tiến.

---

## 1. Sơ đồ luồng hoạt động tổng thể (Improved System Workflow)

```mermaid
flowchart TD
    %% Khởi động hệ thống
    USER([👤 Người dùng]) --> P0_PRE["⚙️ Pha 0: Tiền xử lý quyết định cũ (Deferred Reflection)"]
    
    %% Pha 0: Đọc bộ nhớ cải tiến
    P0_PRE --> P0_MEM{"Tích hợp bộ nhớ Vector\n(vector_memory_enabled)?"}
    P0_MEM -- "Bật & Có thư viện" --> P0_CHROMA["🟩 Bước 1: Lấy nhãn regime phiên trước\n🟩 Bước 2: Truy vấn ChromaDB qua Cosine Similarity\n(Chỉ lấy ký ức có nhãn regime trùng khớp)"]
    P0_MEM -- "Tắt hoặc Fallback" --> P0_FIFO["🟦 Lấy bộ nhớ theo cơ chế FIFO truyền thống"]
    
    P0_CHROMA --> P0_INIT["Khởi tạo AgentState với past_context phù hợp"]
    P0_FIFO --> P0_INIT
    
    %% Pha 1: Tầng phân tích mở rộng
    P0_INIT --> P1_ANALYST["📊 Pha 1: Tầng phân tích đa chiều (Analyst Nodes)"]
    
    subgraph P1_ANALYST_SUB["Chi tiết Tầng Phân Tích"]
        direction TB
        A1["Market Analyst\n(Nếu crypto: gọi get_crypto_indicators\nđể có FNG, DOM, FR, OI)"]
        A2["Sentiment Analyst\n(Mô hình tinh chỉnh qwen3:4b\nxuất báo cáo chuẩn 5 phần)"]
        A3["News Analyst & Fundamentals Analyst"]
        A4["Regime Analyst\n(Chạy TensorFlow HMM phân loại\nBull / Bear / Sideway)"]
    end
    
    P1_ANALYST_SUB --> P2_DEBATE["⚔️ Pha 2: Tranh luận thích ứng (Adaptive Debate)"]
    
    %% Pha 2: Tranh luận thích ứng
    subgraph P2_DEBATE_SUB["Chi tiết Tranh Luận Thích Ứng"]
        direction TB
        B1["Bull Researcher sinh lập luận\n+ Báo cáo điểm CONFIDENCE: X.XX"]
        B2["Bear Researcher sinh lập luận\n+ Báo cáo điểm CONFIDENCE: X.XX"]
        B_COND{"Quyết định dừng tranh luận?\nS_k = 1 - |C_bull - C_bear|\nS_k >= θ (0.75) hoặc count >= 6?"}
        
        B1 --> B2 --> B_COND
        B_COND -- "Chưa đồng thuận" --> B1
    end
    
    %% Các pha quản lý và ra quyết định
    B_COND -- "Đã đồng thuận / Đạt giới hạn" --> P3_MGR["📋 Pha 3: Research Manager tổng hợp luận điểm"]
    P3_MGR --> P4_TRADER["💹 Pha 4: Trader đưa khuyến nghị (Buy/Hold/Sell)"]
    P4_TRADER --> P5_RISK["🛡️ Pha 5: Risk Debate (Aggressive vs Conservative vs Neutral)"]
    P5_RISK --> P6_PM["💼 Pha 6: Portfolio Manager ra quyết định phân bổ vốn\n(Sử dụng nhãn HMM Regime để tăng/giảm tỷ trọng rủi ro)"]
    
    %% Pha 7: Nhật ký và phản hồi trì hoãn
    P6_PM --> P7_POST["💾 Pha 7: Lưu trạng thái quyết định dạng 'pending'"]
    P7_POST --> P7_CACHE["🟩 Ghi nhớ nhãn HMM Regime hiện tại làm dữ liệu đầu vào\ncho lần truy xuất bộ nhớ tiếp theo"]
    
    P7_CACHE --> END([Kết thúc Phiên Giao dịch])
```

---

## 2. Chi tiết cơ chế tương tác giữa các thành phần mới

### A. Tương tác giữa HMM Regime (Trụ cột B) và Vector Memory (Trụ cột C2)
*   **Vòng lặp kín của pha thị trường:** Ở cuối phiên giao dịch trước, nhãn thị trường do tác tử HMM dự báo (ví dụ: `Bear`) được lưu tạm thời vào biến trạng thái chạy của đồ thị (`self._last_regime`).
*   **Truy xuất thông tin phù hợp:** Ở đầu phiên giao dịch tiếp theo, phương thức `get_past_context(regime=...)` nhận tham số `Bear` này. Tác tử `RegimeAwareVectorMemory` sẽ lọc toàn bộ dữ liệu trong ChromaDB thông qua điều kiện `where={"regime": "Bear"}`. Do đó, tác tử Portfolio Manager ở chu kỳ mới sẽ chỉ được tiếp nhận các bài học kinh nghiệm trong quá khứ diễn ra vào đúng pha thị trường đi xuống, loại bỏ hoàn toàn việc nhiễu thông tin từ pha tăng giá trước đó.

### B. Cơ chế dừng sớm của Tranh luận thích ứng (Trụ cột D)
*   Mỗi khi Bull Researcher và Bear Researcher đưa ra câu trả lời, hệ thống sử dụng biểu thức chính quy (Regex) để trích xuất điểm số tin cậy ở cuối văn bản (`CONFIDENCE: <giá trị từ 0.00 đến 1.00>`).
*   Bộ lọc điều hướng `should_continue_debate` của `ConditionalLogic` thực hiện tính toán độ đồng thuận sau mỗi lượt phản hồi của hai bên.
*   Nếu $S_k = 1 - |C_{bull} - C_{bear}| \ge 0.75$, đồ thị lập tức chuyển hướng sang node **Research Manager** mà không chạy các vòng tranh luận tiếp theo, giúp tiết kiệm trung bình 28% lượng token cần thiết cho phiên hội thoại.

### C. Cơ chế nạp chỉ báo Crypto động (Trụ cột D)
*   Trong Market Analyst node, khi hệ thống phát hiện `asset_type == "crypto"`, danh sách công cụ sẽ được bổ sung thêm công cụ `get_crypto_indicators` và hệ thống sẽ mở rộng câu lệnh hệ thống (System Prompt) với hướng dẫn cụ thể về cách đọc FNG, DOM, Funding Rate và Open Interest.
*   Market Analyst sẽ thực hiện gọi công cụ này để nhận về chuỗi dữ liệu trạng thái đòn bẩy và squeeze rủi ro, hỗ trợ đắc lực cho việc đưa ra các luận điểm tranh luận sát với thực tế thị trường tiền mã hóa.
