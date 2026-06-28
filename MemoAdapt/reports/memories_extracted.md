# Báo cáo trích xuất bộ nhớ MeMo

Tài liệu này mô tả toàn bộ 13 bài học hiện có trong memory bank dùng cho Arm B (`Ours + Memory`) của thực nghiệm Q1/2024. Bộ nhớ được chia thành hai nhóm:

- 8 seed memories rút ra từ giai đoạn thị trường giảm năm 2022.
- 5 weekly lessons được sinh tự động trong Q1/2024 sau mỗi tuần giao dịch.

Các bài học này không phải nhãn đúng/sai tuyệt đối. Trong pipeline, chúng được dùng như kinh nghiệm ngữ cảnh cho stage quyết định cuối cùng, sau khi đã lọc theo thời điểm `visible_from` để tránh rò rỉ thông tin tương lai.

## 1. Seed memories từ chu kỳ 2022

Các seed memories được nạp trước khi chạy Q1/2024. Mục tiêu là giúp agent có ký ức về các tình huống bearish, tránh bắt đáy quá sớm và quản trị drawdown tốt hơn.

### 1.1 Bearish Trend Following Underweight

- **Regime**: `bearish_momentum`
- **Nhận định**: AMZN nằm trong trạng thái bearish momentum: giá dưới cả SMA50 và SMA200, MACD âm, lợi nhuận gần đây giảm mạnh. RSI chưa quá bán sâu, nên đây giống tín hiệu xác nhận xu hướng giảm hơn là tín hiệu hồi phục.
- **Nên làm**:
  - Giảm tỷ trọng hoặc giữ trạng thái phòng thủ khi giá dưới cả SMA50 và SMA200.
  - Xem MACD âm kèm chuỗi giảm nhiều ngày là xác nhận xu hướng, không phải tín hiệu mua khi giá giảm.
  - Chờ giá lấy lại ít nhất SMA50 cùng momentum cải thiện trước khi tăng rủi ro.
  - Dùng volume cao trong phiên giảm như xác nhận áp lực bán đang hoạt động.
- **Cần tránh**:
  - Không mua chỉ vì RSI trung tính hoặc giá đã rơi về vùng hỗ trợ cũ.
  - Không đặt quá nhiều trọng số vào bình luận tích cực từ broker khi price action và momentum đang xấu đi.
  - Không xem một phiên bật lại là đảo chiều xu hướng sau nhiều tuần giảm.
  - Không bình quân giá xuống trong regime dưới SMA50/dưới SMA200 và MACD âm.

### 1.2 Regime-Sensitive Hold Bias

- **Regime**: `bearish_momentum`
- **Nhận định**: Trong regime bearish, mặc định nên tránh mở long mới nếu chưa có catalyst đảo chiều rõ. Các prompt có thể phân kỳ giữa Hold và Buy, nhưng nỗ lực Buy trong setup này bị phạt trên reward horizon 1d/5d/20d.
- **Nên làm**:
  - Mặc định Hold khi giá dưới SMA50/SMA200 và MACD âm.
  - Chỉ mở long khi có xác nhận đảo chiều: lấy lại SMA50, RSI cải thiện, MACD cắt lên hoặc có inflection rõ.
  - Dùng horizon 20 ngày làm bộ lọc chính; nếu xu hướng dài hơn vẫn âm, tránh các lệnh mua ngược xu hướng.
- **Cần tránh**:
  - Không mua chỉ vì cổ phiếu quá bán hoặc headline có vẻ hỗ trợ.
  - Không xem volume vừa phải là breakout tăng giá.
  - Không tăng vị thế khi trend stack vẫn bearish.

### 1.3 Risk Off Trend Following

- **Regime**: `bearish_momentum`
- **Nhận định**: AMZN ở trạng thái bearish có độ tin cậy cao: giá dưới SMA50 và SMA200, RSI yếu, MACD âm, return gần đây giảm mạnh với volume cao. Trong chế độ này, xu hướng trước đó thường quan trọng hơn các tín hiệu cơ bản lẫn nhịp hồi ngắn hạn.
- **Nên làm**:
  - Giảm tỷ trọng khi giá dưới SMA50/SMA200 và MACD âm.
  - Đòi hỏi xác nhận đảo chiều trước khi nâng lên Buy.
  - Xem volume cao là xác nhận bán trừ khi giá cũng phá lên vùng kháng cự.
- **Cần tránh**:
  - Không mua chỉ vì có nhịp hồi ngắn hạn hoặc tin tức hỗ trợ rời rạc.
  - Không xem một ngày hồi phục là đổi regime khi RSI còn yếu và MACD còn âm.
  - Không để optimism từ một vài cập nhật kinh doanh lấn át xu hướng giá.

### 1.4 Trend Continuation Short Bias

- **Regime**: `bearish_momentum`
- **Nhận định**: Giá dưới cả hai đường trung bình, RSI yếu, MACD âm và return gần đây giảm mạnh. Đây là tình huống mà xác suất tiếp diễn giảm có tính hành động cao hơn mean reversion.
- **Nên làm**:
  - Ưu tiên Sell hoặc giảm exposure khi trend và momentum cùng bearish.
  - Dùng volume cao ở phiên giảm như dấu hiệu thị trường chấp nhận nhịp giảm.
  - Ưu tiên continuation hơn mean reversion khi horizon 20 ngày chi phối scoring.
- **Cần tránh**:
  - Tránh Hold khi toàn bộ tín hiệu trend và momentum đều bearish.
  - Tránh kỳ vọng tin tốt sẽ cứu vị thế nếu price action tiếp tục yếu.
  - Tránh xem RSI yếu một mình là setup bật lại khi xu hướng lớn vẫn giảm.

### 1.5 State-Specific Trade-Off

- **Regime**: `bullish_momentum`
- **Nhận định**: AMZN ở pha chuyển tiếp bullish mong manh: giá trên SMA50 nhưng vẫn dưới SMA200, RSI trung tính, MACD chỉ hơi dương và return gần đây vẫn âm. Đây có thể là nhịp hồi trong downtrend lớn hơn.
- **Nên làm**:
  - Bán hoặc giảm tỷ trọng khi giá chỉ mới lấy lại SMA ngắn hạn nhưng vẫn dưới SMA dài hạn sau một nhịp giảm mạnh.
  - Ưu tiên giảm rủi ro nếu MACD dương nhưng gần 0 và RSI trung tính.
  - Dùng nhịp hồi để de-risk khi rebound chưa có momentum mở rộng.
- **Cần tránh**:
  - Tránh Hold nếu nhịp tăng chỉ là relief bounce trong cấu trúc bearish lớn.
  - Tránh giả định MACD dương đơn lẻ đồng nghĩa xu hướng đã hồi phục.
  - Tránh chờ SMA200 như xác nhận duy nhất nếu drawdown gần đây vẫn chi phối.

### 1.6 Event Risk Momentum Split

- **Regime**: `bullish_momentum`
- **Nhận định**: AMZN có setup momentum tích cực nhưng nằm ngay trước earnings. Đây là điểm có phương sai cao: cùng một tín hiệu kỹ thuật có thể dẫn tới Buy hoặc Hold tùy prompt ưu tiên continuation hay né event risk.
- **Nên làm**:
  - Buy khi giá trên SMA50, RSI mạnh, MACD dương và volume xác nhận.
  - Xem pre-earnings momentum là có thể giao dịch nếu setup kỹ thuật đã đồng thuận và nhịp tăng đang diễn ra.
  - Ưu tiên tham gia khi scorer thưởng continuation 5d/20d và chưa có dấu hiệu exhaustion.
- **Cần tránh**:
  - Không tự động Hold chỉ vì earnings sắp diễn ra.
  - Không để logic macro-defensive triệt tiêu một momentum signal sạch nếu không có bằng chứng đảo chiều.
  - Không dùng việc còn gần SMA200 như lý do chờ đợi khi short-term trend đã rõ.

### 1.7 Trajectory Reflection: contrarian reversal candidate

- **Regime**: `bearish_momentum`
- **Nhận định**: AMZN có bearish momentum rõ, nhưng cùng input lại sinh các hành động trái ngược. Weighted scorer có lúc thưởng đường đi bắt được nhịp hồi lớn hơn ở horizon 20 ngày.
- **Nên làm**:
  - Xem setup là ứng viên đảo chiều contrarian, không chỉ là trend-following giảm.
  - Có thể dùng Buy nhỏ hoặc starter long khi giá yếu nhưng đã căng và mục tiêu tối ưu là reward 5d/20d.
  - Chấp nhận nhiễu âm 1 ngày và đánh giá theo follow-through nhiều ngày.
- **Cần tránh**:
  - Không tự động Underweight/flat chỉ vì giá dưới cả hai đường trung bình.
  - Không phản ứng quá mức với MACD/RSI âm bằng cách mặc định giảm tiếp ngay.
  - Không dùng bài học này cho lệnh quá ngắn hạn khi outcome 1 ngày chi phối.

### 1.8 Trajectory Reflection: fading extended decline

- **Regime**: `bearish_momentum`
- **Nhận định**: AMZN giảm sâu dưới SMA50/SMA200, RSI yếu, MACD âm và volume cao. Đây là trạng thái momentum-break mạnh, nhưng cũng có thể tạo phân kỳ giữa việc tiếp tục tôn trọng xu hướng và việc fade nhịp giảm quá dài.
- **Nên làm**:
  - Xem selloff sâu dưới SMA50/SMA200 là trạng thái phá vỡ momentum quan trọng.
  - Chỉ cân nhắc Buy chiến thuật nhỏ nếu oversold đi kèm bằng chứng đảo chiều.
  - Dùng sizing nhỏ và giới hạn rủi ro rõ khi giao dịch ngược xu hướng.
- **Cần tránh**:
  - Không mặc định Underweight chỉ vì cổ phiếu đã giảm mạnh.
  - Không giả định bearish momentum luôn tiếp diễn trên mọi horizon 1d/5d/20d.
  - Không tăng vị thế mạnh khi chưa có catalyst đảo chiều.

## 2. Weekly lessons trong Q1/2024

Các weekly lessons được sinh tự động ở cuối từng tuần giao dịch. Chúng tóm tắt tần suất hành động đã xảy ra và nhắc agent dùng decision ledger trước khi thay đổi exposure trong tuần kế tiếp.

### 2.1 Tuần 2024-01-02 đến 2024-01-05

- **Actions taken**: `AAPL: Hold` 8, `GOOGL: Buy` 6, `GOOGL: Underweight` 6, `AMZN: Buy` 5, `AMZN: Underweight` 4, `AMZN: Hold` 3, `AAPL: Buy` 2, `AAPL: Underweight` 2.
- **Bài học tình huống**: Với setup giống tuần này, cần so sánh technical/news evidence hiện tại với decision ledger gần nhất trước khi đổi exposure. Không xem momentum đơn lẻ là đủ; cần thêm support/resistance, risk và xác nhận macro/social.

### 2.2 Tuần 2024-01-08 đến 2024-01-12

- **Actions taken**: `GOOGL: Buy` 8, `AMZN: Underweight` 7, `AMZN: Buy` 7, `AAPL: Buy` 6, `AAPL: Hold` 5, `GOOGL: Underweight` 5, `AAPL: Underweight` 4, `GOOGL: Hold` 2, `AMZN: Hold` 1.
- **Bài học tình huống**: Khi tín hiệu mua và giảm tỷ trọng xuất hiện đồng thời, agent cần kiểm tra liệu quyết định mới có đang lặp lại bias của tuần trước hay có bằng chứng mới đủ mạnh để thay đổi vị thế.

### 2.3 Tuần 2024-01-15 đến 2024-01-19

- **Actions taken**: `GOOGL: Buy` 6, `GOOGL: Underweight` 6, `AAPL: Underweight` 5, `AAPL: Buy` 5, `AMZN: Hold` 4, `AMZN: Buy` 4, `AMZN: Underweight` 4, `AAPL: Hold` 2.
- **Bài học tình huống**: Khi action phân tán gần như cân bằng, không nên tăng hoặc giảm vị thế chỉ dựa vào một nhóm tín hiệu. Cần buộc prompt nêu rõ luận cứ vì sao evidence hiện tại khác tuần trước.

### 2.4 Tuần 2024-01-22 đến 2024-01-26

- **Actions taken**: `AMZN: Hold` 8, `GOOGL: Hold` 7, `AAPL: Hold` 5, `AAPL: Buy` 5, `GOOGL: Underweight` 5, `AAPL: Underweight` 4, `AMZN: Buy` 4, `AMZN: Underweight` 3, `GOOGL: Buy` 3.
- **Bài học tình huống**: Khi Hold chiếm ưu thế, agent nên xem đây là tín hiệu yêu cầu xác nhận cao hơn trước khi thay đổi exposure, đặc biệt nếu risk và macro/social chưa đồng thuận.

### 2.5 Tuần 2024-01-29 đến 2024-01-31

- **Actions taken**: `AAPL: Hold` 7, `AMZN: Hold` 6, `GOOGL: Hold` 6, `AMZN: Buy` 2, `GOOGL: Underweight` 2, `GOOGL: Buy` 1, `AAPL: Underweight` 1, `AMZN: Underweight` 1.
- **Bài học tình huống**: Trong tuần ngắn và tín hiệu thiên về Hold, memory nên khuyến khích agent tránh overtrading. Chỉ tăng hoặc giảm vị thế khi có bằng chứng mới rõ ràng hơn decision ledger hiện tại.

## 3. Cách bộ nhớ được dùng trong quyết định

Khi chạy Arm B, runner chỉ đưa tối đa 5 memory phù hợp nhất vào context cuối:

- Memory chưa đến `visible_from` bị loại để tránh leakage.
- Memory cùng symbol được cộng điểm.
- Memory cùng regime được cộng điểm, nhưng không bắt buộc phải cùng regime.
- Memory có nội dung về rủi ro hoặc bài học từ outcome âm được cộng thêm điểm.
- Memory chỉ được inject ở stage `portfolio_manager_final_decision`.

Điều này giúp memory đóng vai trò như lớp kinh nghiệm bổ sung, không thay thế dữ liệu point-in-time của ngày đang phân tích.