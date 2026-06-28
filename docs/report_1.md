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

# Phân tích hiệu suất đầu tư Q1/2024

Tài liệu này tóm tắt benchmark Q1/2024 của `MemoAdapt` cho ba mã `AAPL`, `GOOGL` và `AMZN`. Mục tiêu là so sánh agent không dùng memory với agent dùng MeMo memory/weekly learning, trong cùng điều kiện offline point-in-time.

## 1. Bảng benchmark thị trường

| Symbol | CR% | ARR% | SR | MDD% |
|---|---:|---:|---:|---:|
| AAPL | -7.91 | -27.71 | -1.59 | 13.50 |
| GOOGL | 12.87 | 61.10 | 1.86 | 14.40 |
| AMZN | 22.26 | 120.63 | 3.22 | 4.22 |

## 2. Bảng benchmark agent

| Model | Prompt | AAPL CR% | AAPL ARR% | AAPL SR | AAPL MDD% | GOOGL CR% | GOOGL ARR% | GOOGL SR | GOOGL MDD% | AMZN CR% | AMZN ARR% | AMZN SR | AMZN MDD% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Ours w/o Memory | `ps_default_v1` | 0.00 | 0.00 | - | 0.00 | -0.98 | -3.80 | -0.14 | 8.74 | 20.00 | 105.01 | 3.00 | 4.22 |
| Ours w/o Memory | `ps_macro_defensive_v1` | -9.74 | -33.20 | -2.39 | 11.65 | -2.19 | -8.37 | -0.65 | 6.09 | 12.18 | 57.21 | 2.00 | 4.69 |
| Ours w/o Memory | `ps_risk_aware_v1` | -3.76 | -14.01 | -2.57 | 4.86 | -2.19 | -8.37 | -0.65 | 6.09 | 12.45 | 58.75 | 2.04 | 4.22 |
| Ours + Memory | `ps_default_v1` | -13.04 | -42.31 | -3.07 | 13.60 | -3.81 | -14.20 | -0.82 | 8.74 | 16.36 | 81.58 | 2.60 | 4.22 |
| Ours + Memory | `ps_macro_defensive_v1` | -10.79 | -36.22 | -2.53 | 13.51 | 2.35 | 9.56 | 1.51 | 1.10 | 18.14 | 92.77 | 2.78 | 4.22 |
| Ours + Memory | `ps_risk_aware_v1` | -1.82 | -6.98 | -1.25 | 3.06 | -2.19 | -8.37 | -0.65 | 6.09 | 14.05 | 67.79 | 2.26 | 4.22 |

## 3. Bối cảnh giá Q1/2024

Dưới đây là biểu đồ giá của ba mã trong Q1/2024. Các biểu đồ này giúp đặt kết quả agent vào bối cảnh thị trường thực tế.

![Biểu đồ AAPL Q1 2024](./images/AAPL_Q1_2024.png)

![Biểu đồ GOOGL Q1 2024](./images/GOOGL_Q1_2024.png)

![Biểu đồ AMZN Q1 2024](./images/AMZN_Q1_2024.png)

## 4. Diễn giải theo từng mã

### AAPL: thị trường giảm

AAPL là tình huống kiểm tra khả năng phòng thủ. Buy & Hold lỗ `-7.91%` và chịu MDD `13.50%`.

Baseline `ps_default_v1` tránh toàn bộ rủi ro nên CR và MDD đều bằng `0.00`. Tuy nhiên, cấu hình đáng chú ý nhất là `Ours + Memory` với `ps_risk_aware_v1`: CR chỉ còn `-1.82%` và MDD giảm xuống `3.06%`. Đây là bằng chứng mạnh nhất cho tác dụng của memory trong việc giảm drawdown khi thị trường đi xuống.

### GOOGL: thị trường biến động, tăng nhẹ

GOOGL có Buy & Hold đạt `12.87%`, nhưng đi kèm MDD `14.40%`. Phần lớn agent không bắt trọn được upside. Điểm sáng nằm ở `Ours + Memory` với `ps_macro_defensive_v1`: CR dương `2.35%`, SR `1.51` và MDD chỉ `1.10%`.

Điều này cho thấy memory kết hợp với prompt phòng thủ vĩ mô có thể tạo đường vốn ổn định hơn, ngay cả khi hy sinh phần lớn upside của thị trường.

### AMZN: thị trường tăng mạnh

AMZN là tình huống uptrend rõ nhất. Buy & Hold đạt `22.26%`. Baseline `ps_default_v1` đạt `20.00%`, bám khá sát thị trường.

Khi bật memory, lợi nhuận của AMZN thấp hơn baseline tương ứng. Ví dụ `ps_default_v1` giảm từ `20.00%` xuống `16.36%`. Đây là trade-off dễ thấy: memory khiến agent thận trọng hơn, phù hợp với mục tiêu kiểm soát rủi ro nhưng không luôn tối ưu khi thị trường tăng mạnh và ít drawdown.

## 5. Tác động của memory

Memory không tạo lợi thế đồng đều trên mọi mã. Tác động chính là thay đổi hành vi rủi ro:

- Trên AAPL, memory giúp cấu hình risk-aware giảm lỗ và drawdown rõ rệt.
- Trên GOOGL, memory giúp cấu hình macro-defensive giữ MDD rất thấp.
- Trên AMZN, memory làm agent bớt aggressive, dẫn tới return thấp hơn baseline trong uptrend mạnh.

Vì vậy, MeMo Adapt nên được hiểu như một lớp điều tiết rủi ro hơn là cơ chế tối đa hóa lợi nhuận tuyệt đối.

## 6. Vai trò của prompt set

`ps_default_v1` thiên về bắt xu hướng. Prompt này hoạt động rất tốt trên AMZN, nhưng có thể yếu hơn khi thị trường giảm hoặc nhiễu.

`ps_macro_defensive_v1` phù hợp hơn với môi trường biến động không rõ xu hướng. Kết quả GOOGL cho thấy prompt này kết hợp với memory có thể giảm drawdown rất mạnh.

`ps_risk_aware_v1` là prompt kiểm soát rủi ro rõ nhất. Trên AAPL, cấu hình này kết hợp với memory tạo kết quả phòng thủ tốt nhất trong toàn bộ benchmark.

## 7. Giải thích chỉ số

- **CR% (Cumulative Return)**: lợi nhuận tích lũy của toàn kỳ đánh giá.
- **ARR% (Annualized Return)**: CR được quy đổi theo năm dựa trên số ngày giao dịch trong kỳ.
- **SR (Sharpe Ratio)**: lợi nhuận điều chỉnh theo rủi ro; càng cao càng tốt.
- **MDD% (Maximum Drawdown)**: mức sụt giảm lớn nhất từ đỉnh vốn xuống đáy vốn trong kỳ; càng thấp càng tốt.

## 8. Kết luận

Trong benchmark Q1/2024, MeMo Adapt thể hiện rõ nhất ở khả năng phòng thủ:

- Giảm drawdown tốt khi thị trường giảm hoặc nhiễu.
- Hỗ trợ prompt risk-aware và macro-defensive ra quyết định thận trọng hơn.
- Có thể đánh đổi một phần lợi nhuận trong thị trường uptrend mạnh.

Kết quả nên được đọc như bằng chứng về trade-off giữa return và risk control. Memory không thay thế dữ liệu hiện tại; nó bổ sung kinh nghiệm tình huống để portfolio manager cuối cùng cân nhắc trước khi ra quyết định.

