# PHẦN 2: CÁC HẠN CHẾ CỐT LÕI CỦA HỆ THỐNG SOTA GỐC (TRADINGAGENTS)

Để nâng cấp hệ thống giao dịch đa tác tử lên mức State-of-the-Art thực tế, chúng tôi đã tiến hành phân tích sâu kiến trúc và code gốc của `TradingAgents`. Đối chiếu với các phản biện từ cộng đồng nghiên cứu tài chính định lượng, chúng tôi xác định được **7 hạn chế cốt lõi** sau đây. Mỗi hạn chế này chính là động lực thúc đẩy cho một trụ cột cải tiến tương ứng.

---

## 1. Chất lượng tầng Sentiment bị phụ thuộc vào mô hình nền
*   **Hạn chế:** Trong hệ thống gốc, tác tử Sentiment Analyst sử dụng trực tiếp mô hình ngôn ngữ lớn (LLM) thông dụng (như GPT-4o hoặc các model mã nguồn mở phổ thông) mà không qua tinh chỉnh chuyên sâu về tài chính.
*   **Hệ quả:** Các mô hình nhỏ dễ bị nhiễu bởi văn phong không chính thống trên mạng xã hội (Reddit, StockTwits), dẫn đến phân loại sai hướng tâm lý. Ngoài ra, báo cáo đầu ra của Sentiment Analyst thường thiếu cấu trúc đồng nhất, lúc có bảng so sánh lúc không, tạo ra thông tin đầu vào không đáng tin cậy cho toàn bộ pipeline phía sau.

## 2. Thiếu nhận thức về pha thị trường (Regime-Unawareness)
*   **Hạn chế:** Hệ thống đưa ra quyết định giao dịch mà hoàn toàn không có khái niệm về xu hướng vĩ mô dài hạn của thị trường (Bull Market - Thị trường giá lên, Bear Market - Thị trường giá xuống, Sideway - Thị trường đi ngang).
*   **Hệ quả:** Việc phân bổ tỷ trọng vốn (`target_weight`) của Portfolio Manager diễn ra thiếu nhất quán. Hệ thống dễ dàng mua mạnh khi thị trường đang rơi vào chu kỳ sụt giảm sâu (Bear), dẫn đến mức sụt giảm tài sản lớn (Drawdown) không thể kiểm soát.

## 3. Không có bộ nhớ tích lũy dài hạn (No Long-Term Memory Bank)
*   **Hạn chế:** Mỗi phiên giao dịch của tác tử gần như là một quy trình đơn lẻ "làm lại từ đầu". Hệ thống không lưu trữ các bài học kinh nghiệm dài hạn từ các chu kỳ thị trường khắc nghiệt trong lịch sử (ví dụ: chu kỳ sụt giảm sâu năm 2022).
*   **Hệ quả:** Hệ thống liên tục lặp lại các sai lầm kinh điển như: trung bình giá xuống (average-down) quá sớm trong xu thế giảm mạnh, hoặc mua đuổi (FOMO) tại đỉnh các đợt sóng hồi kỹ thuật.

## 4. Cơ chế truy xuất ký ức tuần tự thô sơ (FIFO Memory Retrieval)
*   **Hạn chế:** Bộ nhớ nhật ký phản hồi (`TradingMemoryLog`) của hệ thống gốc chỉ hỗ trợ truy xuất theo kiểu FIFO (First-In, First-Out - Lấy các phiên gần nhất theo thời gian).
*   **Hệ quả:** Lấy ký ức "gần nhất" thay vì "liên quan nhất". Bài học của một tuần tăng giá mạnh (Bull) ngay trước đó sẽ bị đưa vào làm ngữ cảnh khi thị trường vừa đột ngột đảo chiều giảm sâu (Bear), dẫn đến việc áp dụng sai kinh nghiệm và ra quyết định giao dịch sai lầm (non-stationarity).

## 5. Số vòng tranh luận cố định (Fixed Debate Rounds)
*   **Hạn chế:** Lớp tranh luận học thuật giữa Bull Researcher và Bear Researcher được cấu hình cố định $K = 3$ vòng back-and-forth cho mọi tình huống.
*   **Hệ quả:** 
    *   **Lãng phí token:** Khi tín hiệu thị trường cực kỳ rõ ràng (ví dụ: xu hướng tăng/giảm mạnh không thể bàn cãi), hệ thống vẫn bắt buộc các tác tử phải tranh luận đủ số vòng, làm tăng chi phí API và độ trễ hệ thống một cách vô ích.
    *   **Quyết định ẩu:** Khi thị trường nhiễu động mạnh, 3 vòng tranh luận có thể chưa đủ để hai bên đạt tới sự đồng thuận hoặc làm rõ các rủi ro ẩn giấu.

## 6. Thiếu các chỉ báo đặc trưng cho thị trường Tiền mã hóa (Crypto-native Indicators)
*   **Hạn chế:** Hệ thống sử dụng chung một bộ công cụ tính chỉ báo kỹ thuật của cổ phiếu truyền thống cho tất cả các loại tài sản.
*   **Hệ quả:** Khi phân tích các tài sản mã hóa (BTC, ETH), hệ thống hoàn toàn bỏ lỡ các thông tin cực kỳ quan trọng về dòng tiền phái sinh và tâm lý cực đoan trên chuỗi (như Chỉ số Sợ hãi & Tham lam - Fear & Greed Index, Tỷ lệ Thống trị của BTC - BTC Dominance, Tỷ lệ Lệ phí Tài trợ - Funding Rate, và Hợp đồng Mở - Open Interest). Điều này khiến tác tử phân tích thị trường bị mù thông tin đòn bẩy và dễ bị thanh lý trong các đợt biến động mạnh.

## 7. Rủi ro rò rỉ thông tin tương lai (Look-Ahead Bias)
*   **Hạn chế:** Các kiểm thử của hệ thống gốc thường gặp lỗi rò rỉ dữ liệu tương lai (temporal contamination) khi tính toán chỉ báo hoặc khi đọc bộ nhớ nhật ký mà không có cơ chế giới hạn thời điểm nhìn thấy (`visible_from`).
*   **Hệ quả:** Kết quả backtest trả về rất đẹp nhưng khi đưa vào giao dịch thực tế (live-trading) thì hiệu năng sụt giảm nghiêm trọng do các tác tử vô tình được đọc thông tin hoặc bài học rút ra từ tương lai của chu kỳ backtest đó.
