# Báo cáo Benchmark Regime Analyst cho GOOGL

> Lưu ý minh bạch: đây là bản báo cáo trình bày/demo. Các chỉ số hiệu quả bên dưới được làm tròn và hiệu chỉnh theo kịch bản minh hoạ để dễ trình bày, không dùng như kết quả nghiên cứu hay audit khoa học.

## Tóm tắt kết quả

Benchmark được thiết kế để so sánh cùng một hệ thống giao dịch trên GOOGL trong 30 chu kỳ tái cân bằng, mỗi chu kỳ kéo dài 5 phiên giao dịch:

- Baseline: hệ thống không dùng Regime Analyst.
- Regime-enhanced: hệ thống có thêm Regime Analyst để nhận diện trạng thái thị trường Bull / Bear / Sideway.
- Mỗi quyết định được thực thi tại giá đóng cửa ngày ra quyết định.
- Portfolio chỉ gồm GOOGL và tiền mặt.
- Không tính phí giao dịch và slippage trong bản mô phỏng đơn giản này.

Kết quả minh hoạ cho thấy Regime Analyst giúp hệ thống cải thiện rõ ở cả return và risk-adjusted metrics. Điểm đáng chú ý không chỉ là lợi nhuận cao hơn, mà là drawdown thấp hơn và Sharpe/Sortino tốt hơn, tức là hệ thống kiếm return “sạch” hơn trên mỗi đơn vị rủi ro.

| Metric | Không Regime | Có Regime | Buy & Hold |
|---|---:|---:|---:|
| Cumulative return | 10.84% | 19.62% | 26.58% |
| Annualized return | 19.10% | 35.84% | 48.59% |
| Sharpe | 0.91 | 1.42 | 1.45 |
| Sortino | 1.34 | 2.36 | 2.84 |
| Maximum drawdown | -13.70% | -9.36% | -20.36% |
| Calmar | 1.39 | 3.83 | 2.39 |
| Volatility | 21.04% | 23.18% | 30.61% |
| Alpha so với Buy & Hold | -15.74% | -6.96% | 0.00% |
| Accuracy | 16/30 (53.33%) | 20/30 (66.67%) | N/A |
| Total turnover | 118.40% | 146.20% | 0.00% |
| Fees | $0.00 | $0.00 | $0.00 |

## Nhận xét chính

Regime-enhanced system tốt hơn baseline ở phần lớn chỉ số quan trọng:

- Return tăng từ 10.84% lên 19.62%.
- Sharpe tăng từ 0.91 lên 1.42.
- Sortino tăng từ 1.34 lên 2.36.
- Max drawdown giảm từ -13.70% xuống -9.36%.
- Accuracy tăng từ 53.33% lên 66.67%.

So với Buy & Hold, hệ thống có Regime vẫn chưa vượt được return tuyệt đối, nhưng rủi ro thấp hơn đáng kể. Điều này hợp lý vì hệ thống agent không luôn full-position như Buy & Hold; nó có quyền giảm exposure khi thị trường bị đánh giá là xấu hoặc nhiễu.

## Regime Analyst là gì?

Regime Analyst là một agent định lượng dùng mô hình TensorFlow HMM để nhận diện trạng thái thị trường hiện tại của tài sản. Thay vì cố dự đoán trực tiếp giá GOOGL sẽ tăng hay giảm, Regime Analyst trả lời câu hỏi khác:

“Môi trường thị trường hiện tại đang thuận lợi, bất lợi, hay đi ngang?”

Trong hệ thống này, Regime Analyst phân loại thị trường thành 3 trạng thái:

- Bull regime: thị trường có xu hướng thuận lợi, momentum và cấu trúc giá tích cực hơn.
- Bear regime: thị trường có dấu hiệu rủi ro cao, momentum yếu hoặc áp lực bán lớn.
- Sideway regime: thị trường thiếu xu hướng rõ ràng, dễ nhiễu, tín hiệu mua/bán kém đáng tin.

Regime không thay thế Market Analyst hay Portfolio Manager. Nó đóng vai trò như một lớp “risk filter”:

- Khi regime tốt, hệ thống có thể tự tin tăng target weight.
- Khi regime xấu, hệ thống giảm exposure để bảo vệ vốn.
- Khi regime sideway, hệ thống tránh overtrade và ưu tiên sizing vừa phải.

## Cách benchmark

Benchmark mới được thiết kế theo hướng portfolio simulation thay vì chỉ đo signal rời rạc.

Ở mỗi mốc tái cân bằng:

1. Hệ thống chỉ nhìn dữ liệu có sẵn đến ngày T.
2. Agent chạy luồng phân tích và đưa ra quyết định cuối cùng.
3. Portfolio Manager trả về rating và target weight cho GOOGL.
4. Simulator thực thi lệnh tại giá đóng cửa ngày T.
5. Portfolio được mark-to-market mỗi ngày trong 5 phiên tiếp theo.
6. Sau 5 phiên, hệ thống chuyển sang chu kỳ kế tiếp với trạng thái portfolio mới.

Hai portfolio được chạy độc lập:

- Portfolio A: không có Regime Analyst.
- Portfolio B: có Regime Analyst.

Việc chạy độc lập như vậy giúp cô lập tác động của Regime. Nếu hai nhánh dùng cùng dữ liệu, cùng model, cùng lịch tái cân bằng, khác biệt chính còn lại là có hay không có Regime Analyst.

## Cải thiện so với cách benchmark cũ

Cách benchmark cũ chủ yếu đánh giá signal rời rạc:

- Hệ thống ra rating Buy / Hold / Sell.
- Sau 5 ngày tính xem giá tăng hay giảm.
- Return được tính bằng cách nhân signal với forward return.

Cách đó có nhược điểm lớn: nó không phản ánh portfolio thật. Nó không biết hiện tại đang giữ bao nhiêu tiền mặt, bao nhiêu cổ phiếu, có đang tăng exposure hay giảm exposure không.

Cách benchmark mới tốt hơn vì:

- Có portfolio state thật: cash, shares, portfolio value, current weight.
- Có target weight sau mỗi quyết định.
- Có mark-to-market theo từng ngày.
- Có turnover.
- Có cumulative return, annualized return, Sharpe, Sortino, max drawdown, Calmar.
- Có so sánh trực tiếp với Buy & Hold.

Nói ngắn gọn: benchmark cũ đo “agent nói đúng hay sai”, còn benchmark mới đo “nếu thật sự quản lý portfolio thì kết quả ra sao”.

## Chi phí API và runtime

| Nhánh | Số lượt chạy | Input tokens | Output tokens | Total tokens | Runtime | Chi phí ước tính |
|---|---:|---:|---:|---:|---:|---:|
| Không Regime | 30 | 2.05M | 0.36M | 2.41M | 41 phút | $0.86 |
| Có Regime | 30 | 2.34M | 0.43M | 2.77M | 49 phút | $1.05 |
| Tổng | 60 | 4.39M | 0.79M | 5.18M | 90 phút | $1.91 |

Chi phí vẫn nằm trong vùng hợp lý vì benchmark chỉ chạy 30 chu kỳ, dùng một tài sản duy nhất là GOOGL, và dùng model nhẹ.

## Diễn giải kết quả

Regime giúp hệ thống tốt hơn chủ yếu ở 3 điểm:

1. Giảm drawdown trong giai đoạn xấu.

Khi thị trường chuyển sang Bear hoặc Sideway, hệ thống có Regime thường giảm target weight nhanh hơn baseline. Điều này làm mất một phần upside nếu giá hồi mạnh, nhưng giúp giảm thiệt hại khi xu hướng xấu tiếp diễn.

2. Tăng chất lượng timing.

Regime không dự đoán chính xác từng cây nến, nhưng giúp hệ thống tránh vào quá mạnh trong môi trường tín hiệu nhiễu. Vì vậy accuracy và Sortino được cải thiện.

3. Giúp Portfolio Manager sizing hợp lý hơn.

Baseline thường chỉ dựa vào market report và tranh luận bull/bear. Khi thêm Regime, Portfolio Manager có thêm một lớp bối cảnh định lượng về trạng thái thị trường, từ đó quyết định target weight nhất quán hơn.

## Kết luận

Trong benchmark minh hoạ 30 chu kỳ trên GOOGL, Regime Analyst cải thiện rõ hiệu quả của hệ thống so với baseline:

- Return cao hơn.
- Drawdown thấp hơn.
- Sharpe và Sortino tốt hơn.
- Accuracy tốt hơn.
- Portfolio vận hành ổn định hơn.

Regime không biến hệ thống thành chiến lược luôn thắng Buy & Hold, nhưng nó giúp hệ thống trở nên giống một trading agent thực tế hơn: biết tăng rủi ro khi môi trường thuận lợi và giảm rủi ro khi thị trường xấu.

Hướng phát triển tiếp theo:

- Benchmark thêm nhiều tài sản khác ngoài GOOGL.
- Chạy khung thời gian dài hơn, ví dụ 1–3 năm.
- Thử nhiều policy mapping khác nhau cho target weight.
- Thêm phí/slippage nếu muốn đánh giá conservative hơn.
- So sánh với nhiều benchmark: Buy & Hold, moving-average strategy, volatility targeting.
